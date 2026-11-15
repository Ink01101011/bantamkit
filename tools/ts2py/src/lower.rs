//! TypeScript AST (oxc) to Python source, for the subset `SUBSET.md` lists.
//!
//! Every construct outside the subset is refused with a span and a construct name; lowering keeps
//! going after a refusal so one run reports every offence, and the caller writes nothing when any
//! refusal was recorded.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use oxc_ast::ast::*;
use oxc_span::{GetSpan, Span};

use crate::adapters::{self, AdapterKind};
use crate::pyfmt::{is_py_keyword, py_name, py_number, py_str, py_str_utf16};
use crate::types::{self, Assume, Fact, Key, MODULE, Observed, TypeDecls};

/// One refusal: where, and what construct.
pub struct Refusal {
    pub span: Span,
    pub construct: String,
}

// Python precedence levels, low to high. A child printed below the level its slot needs is
// parenthesised.
const LAMBDA: u8 = 1;
const TERNARY: u8 = 2;
const OR: u8 = 3;
const AND: u8 = 4;
const NOT: u8 = 5;
const CMP: u8 = 6;
const ADD: u8 = 11;
const UNARY: u8 = 13;
const ATOM: u8 = 16;

/// A lowered expression and what is statically known about its value.
#[derive(Clone, Default)]
struct Py {
    code: String,
    prec: u8,
    /// Always a Python `bool`, so it can stand in a condition without `_js_truthy`.
    is_bool: bool,
    /// Always a number that is not a bool, so `===` against a number literal may be `==`.
    is_num: bool,
    /// Always a `str`.
    is_str: bool,
    /// A value a JS double holds exactly (or not a number at all), so `_js_num` would return it
    /// unchanged: a literal, a length, the result of an arithmetic lowering.
    is_double: bool,
    /// Evaluating it has no side effect, so `||`, `&&`, `??` may evaluate it eagerly.
    pure: bool,
    /// J86: a string whose first UTF-16 unit is known not to be a trail surrogate (or that is
    /// empty), so nothing concatenated before it can complete a surrogate pair.
    safe_start: bool,
    /// J86: a string whose last unit is known not to be a lead surrogate (or that is empty).
    safe_end: bool,
    /// J87: always a Python `list` (a JS array).
    is_list: bool,
    /// J87: always a compiled `re.Pattern` without the `g` flag.
    is_regex: bool,
    /// J87: a fresh array of exactly these element facts (`types::Fact::tuple`).
    tuple: Option<Vec<Fact>>,
    /// J87: what every element is (a frozen module array only, `types::Fact::elem`).
    elem: Option<Box<Fact>>,
    /// J87: passed through from a key no round has assigned yet (`types::Fact::top`).
    top: bool,
    /// J87: nullability (`types::Fact::{match_, nn, no_null, no_undef, is_null, is_undef}`).
    is_match: bool,
    nn: Option<Box<Fact>>,
    no_null: bool,
    no_undef: bool,
    is_null: bool,
    is_undef: bool,
}

impl Py {
    fn new(code: impl Into<String>, prec: u8) -> Self {
        Py {
            code: code.into(),
            prec,
            ..Py::default()
        }
    }
    fn atom(code: impl Into<String>) -> Self {
        Py::new(code, ATOM)
    }
    fn boolean(code: impl Into<String>, prec: u8) -> Self {
        Py {
            is_bool: true,
            ..Py::new(code, prec)
        }
    }
    /// J87: what is proven about this value.
    fn fact(&self) -> Fact {
        if self.top {
            return Fact::top();
        }
        Fact {
            str_: self.is_str,
            num: self.is_num && self.is_double,
            bool_: self.is_bool,
            list: self.is_list,
            regex: self.is_regex,
            match_: self.is_match,
            tuple: self.tuple.clone(),
            elem: self.elem.clone(),
            top: false,
            nn: self.nn.clone(),
            no_null: self.no_null,
            no_undef: self.no_undef,
            is_null: self.is_null,
            is_undef: self.is_undef,
        }
    }

    /// J87: this value with `fact` proven too (None: the optimistic first round, everything).
    fn with_fact(mut self, fact: Option<&Fact>) -> Py {
        match fact {
            None | Some(Fact { top: true, .. }) => {
                self.top = true;
                self.is_str = true;
                self.is_num = true;
                self.is_double = true;
                self.is_bool = true;
                self.is_list = true;
                self.is_regex = true;
            }
            Some(f) => {
                self.is_str |= f.str_;
                if f.num {
                    self.is_num = true;
                    self.is_double = true;
                }
                self.is_bool |= f.bool_;
                self.is_list |= f.list;
                self.is_regex |= f.regex;
                self.is_match |= f.match_;
                self.no_null |= f.no_null;
                self.no_undef |= f.no_undef;
                self.is_null |= f.is_null;
                self.is_undef |= f.is_undef;
                if f.tuple.is_some() {
                    self.tuple = f.tuple.clone();
                }
                if f.elem.is_some() {
                    self.elem = f.elem.clone();
                }
                if f.nn.is_some() {
                    self.nn = f.nn.clone();
                }
            }
        }
        self
    }

    /// J87: the facts both `self` and `other` prove, on `code` (a value that is one of the two).
    fn meet_into(&self, other: &Py, code: Py) -> Py {
        let both = self.fact().meet(&other.fact());
        Py {
            is_bool: both.bool_,
            is_num: self.is_num && other.is_num,
            is_double: self.is_double && other.is_double,
            is_str: both.str_,
            is_list: both.list,
            is_regex: both.regex,
            tuple: both.tuple,
            elem: both.elem,
            top: both.top,
            is_match: both.match_,
            nn: both.nn,
            no_null: both.no_null,
            no_undef: both.no_undef,
            is_null: both.is_null,
            is_undef: both.is_undef,
            ..code
        }
    }

    fn at(&self, min: u8) -> String {
        if self.prec < min {
            format!("({})", self.code)
        } else {
            self.code.clone()
        }
    }
}

/// What a builtin method is known to return.
#[derive(Clone, Copy, PartialEq)]
enum Ret {
    Bool,
    Str,
    /// Always a number (never `undefined`).
    Num,
    /// J87: always a `list` (the helper raises on any receiver it would not return one for).
    List,
    /// J87: `None` or a match array (`_js_m_exec`).
    Match,
    Any,
}

/// Methods the subset accepts, with the argument counts each takes and which argument (if any)
/// is a callback that must be an inline arrow.
const METHODS: &[(&str, usize, usize, Option<usize>, Ret)] = &[
    // name, min args, max args, callback index, what it returns
    ("has", 1, 1, None, Ret::Bool),
    ("get", 1, 1, None, Ret::Any),
    ("set", 2, 2, None, Ret::Any),
    ("add", 1, 1, None, Ret::Any),
    ("includes", 1, 1, None, Ret::Bool),
    ("startsWith", 1, 1, None, Ret::Bool),
    ("split", 1, 1, None, Ret::List),
    ("test", 1, 1, None, Ret::Bool),
    ("every", 1, 1, Some(0), Ret::Bool),
    ("some", 1, 1, Some(0), Ret::Bool),
    ("find", 1, 1, Some(0), Ret::Any),
    ("map", 1, 1, Some(0), Ret::List),
    ("push", 1, usize::MAX, None, Ret::Any),
    ("slice", 0, 2, None, Ret::Any),
    ("join", 0, 1, None, Ret::Str),
    ("sort", 0, 1, Some(0), Ret::List),
    ("entries", 0, 0, None, Ret::List),
    // J86 (the fact-file codec).
    ("codePointAt", 0, 1, None, Ret::Any),
    ("indexOf", 1, 2, None, Ret::Num),
    ("lastIndexOf", 1, 2, None, Ret::Num),
    ("padStart", 1, 2, None, Ret::Str),
    ("padEnd", 1, 2, None, Ret::Str),
    ("repeat", 1, 1, None, Ret::Str),
    ("toLowerCase", 0, 0, None, Ret::Str),
    ("toUpperCase", 0, 0, None, Ret::Str),
    ("replace", 2, 2, None, Ret::Str),
    ("exec", 1, 1, None, Ret::Match),
    ("reverse", 0, 0, None, Ret::List),
    ("pop", 0, 0, None, Ret::Any),
    ("filter", 1, 1, Some(0), Ret::List),
    ("toString", 0, 1, None, Ret::Str),
    // J87-3 (#316 G1: jobbudget).
    ("splice", 1, usize::MAX, None, Ret::List),
    ("reduce", 1, 2, Some(0), Ret::Any),
];

/// J86-R finding 3: every method a builtin prototype the subset can reach carries (String, Array,
/// Map, Set, RegExp, Number, Function, Object.prototype), whether or not `METHODS` can call it. A
/// member with one of these names, or a name a compiled or adapter class declares as a method, is
/// CALLABLE, and may only be named as the callee of a direct call: read as a value it is a function
/// in JS (`this` unbound on a later call, identical on every read) and something else in Python (a
/// fresh bound method, or `undefined`). ts2py has no type checker, so the name decides, on every
/// receiver: a refusal is the side that cannot be wrong. `length` and `size` are data, not here.
#[rustfmt::skip]
const JS_METHOD_NAMES: &[&str] = &[
    // String.prototype (Annex B's HTML methods included: they are functions in Node too).
    "anchor", "at", "big", "blink", "bold", "charAt", "charCodeAt", "codePointAt", "concat",
    "endsWith", "fixed", "fontcolor", "fontsize", "includes", "indexOf", "isWellFormed",
    "italics", "lastIndexOf", "link", "localeCompare", "match", "matchAll", "normalize", "padEnd",
    "padStart", "repeat", "replace", "replaceAll", "search", "slice", "small", "split",
    "startsWith", "strike", "sub", "substr", "substring", "sup", "toLocaleLowerCase",
    "toLocaleUpperCase", "toLowerCase", "toUpperCase", "toWellFormed", "trim", "trimEnd",
    "trimLeft", "trimRight", "trimStart",
    // Array.prototype.
    "copyWithin", "entries", "every", "fill", "filter", "find", "findIndex", "findLast",
    "findLastIndex", "flat", "flatMap", "forEach", "join", "keys", "map", "pop", "push", "reduce",
    "reduceRight", "reverse", "shift", "some", "sort", "splice", "toReversed", "toSorted",
    "toSpliced", "unshift", "values", "with",
    // Map.prototype and Set.prototype.
    "add", "clear", "delete", "difference", "get", "has", "intersection", "isDisjointFrom",
    "isSubsetOf", "isSupersetOf", "set", "symmetricDifference", "union",
    // RegExp.prototype, Number.prototype, Function.prototype.
    "compile", "exec", "test", "toExponential", "toFixed", "toPrecision", "apply", "bind", "call",
    // Object.prototype.
    "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__", "constructor",
    "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "toLocaleString", "toString",
    "valueOf",
];

/// Static calls on a builtin namespace: object, method, helper, min args, max args, returns.
const STATIC_CALLS: &[(&str, &str, &str, usize, usize, Ret)] = &[
    ("Array", "isArray", "_js_is_array", 1, 1, Ret::Bool),
    (
        "Number",
        "isInteger",
        "_js_number_is_integer",
        1,
        1,
        Ret::Bool,
    ),
    ("JSON", "stringify", "_js_json_stringify", 1, 1, Ret::Any),
    // J86 (the fact-file codec).
    ("Number", "isNaN", "_js_number_is_nan", 1, 1, Ret::Bool),
    ("Math", "floor", "_js_floor", 1, 1, Ret::Num),
    ("Math", "abs", "_js_abs", 1, 1, Ret::Num),
    ("Math", "max", "_js_max", 0, usize::MAX, Ret::Num),
    ("Math", "min", "_js_min", 0, usize::MAX, Ret::Num),
    ("Object", "keys", "_js_object_keys", 1, 1, Ret::Any),
    ("Object", "entries", "_js_object_entries", 1, 1, Ret::Any),
    ("Object", "freeze", "_js_freeze", 1, 1, Ret::Any),
    (
        "Object",
        "getPrototypeOf",
        "_js_get_prototype_of",
        1,
        1,
        Ret::Any,
    ),
    (
        "String",
        "fromCodePoint",
        "_js_from_code_point",
        0,
        usize::MAX,
        Ret::Str,
    ),
    // J87-3 (#316 G1: pricing, jobbudget).
    ("JSON", "parse", "_js_json_parse", 1, 1, Ret::Any),
    (
        "Number",
        "isFinite",
        "_js_number_is_finite",
        1,
        1,
        Ret::Bool,
    ),
    ("Math", "trunc", "_js_trunc", 1, 1, Ret::Num),
    // J87-3F (#316 G1: own-key price lookups).
    ("Object", "hasOwn", "_js_object_has_own", 2, 2, Ret::Bool),
    (
        "Object",
        "fromEntries",
        "_js_object_from_entries",
        1,
        1,
        Ret::Any,
    ),
];

/// Global functions (J86): name, helper, min args, max args, returns.
const GLOBAL_CALLS: &[(&str, &str, usize, usize, Ret)] = &[
    ("BigInt", "_js_bigint", 1, 1, Ret::Any),
    ("Number", "_js_number", 0, 1, Ret::Num),
    ("String", "_js_str", 1, 1, Ret::Str),
    ("parseInt", "_js_parse_int", 1, 2, Ret::Num),
];

fn returned(ret: Ret, code: String) -> Py {
    Py {
        is_bool: ret == Ret::Bool,
        is_str: ret == Ret::Str,
        is_num: ret == Ret::Num,
        is_double: ret == Ret::Num,
        is_list: ret == Ret::List,
        is_match: ret == Ret::Match,
        ..Py::atom(code)
    }
}

/// What one compiled module exports, as another compiled module imports it (J86).
#[derive(Clone, Default)]
pub struct ModuleExports {
    /// The Python module name (the TypeScript file's stem).
    pub py_module: String,
    /// Source name -> (Python name, is a class).
    pub names: HashMap<String, (String, bool)>,
}

/// Everything about the other modules of a multi-module compile a module needs (J86).
#[derive(Clone, Default)]
pub struct ModuleCtx {
    /// This module's path, as printed (`runtime-ts/src/memory/factfile.ts`).
    pub path: String,
    /// Every compiled module, by its normalised `.ts` path.
    pub modules: HashMap<String, ModuleExports>,
    /// Method names declared by any class in any compiled module, and by the adapter classes.
    pub class_methods: HashSet<String>,
    /// Where the hand-written adapters are imported from (`._ts2py_adapters`).
    pub adapter_module: String,
}

/// A class being lowered: its members as JS spells them.
#[derive(Clone, Default)]
struct ClassCtx {
    /// Fields, methods and getters this class (or a compiled base) declares.
    members: HashSet<String>,
    /// Methods only (callable as `this.m(...)`).
    methods: HashSet<String>,
}

/// What an unlabelled `break` would leave: a loop (Python's `break` does the same) or a `switch`
/// (lowered to an if-chain, so only a trailing `break` is accepted and dropped).
#[derive(Clone, Copy, PartialEq)]
enum BreakTarget {
    Loop,
    Switch,
}

pub struct Lowerer<'s> {
    src: &'s str,
    pub refusals: Vec<Refusal>,
    /// Hoisted regex constants: translated pattern and whether it has the `g` flag, in first-use order.
    regexes: Vec<(String, bool)>,
    /// Module-level source name -> Python name.
    globals: HashMap<String, String>,
    /// J87-3: source names of the Error classes visible here (an adapter `ErrorClass`, or a class
    /// declared here that extends one or `Error`), which a compiled class may extend.
    error_classes: HashSet<String>,
    /// J87-3: source names of adapter functions, which may be passed as a `.sort` comparator.
    adapter_fns: HashSet<String>,
    /// J87-3: the enclosing `catch (e)` bindings, innermost last: (source name, the temporary
    /// holding what was caught). The only use accepted is rethrowing it (`throw e`).
    catch_params: Vec<(String, String)>,
    /// Python names of exported bindings.
    pub exports: Vec<String>,
    /// Local scopes, innermost last: a function's locals, then each enclosing lambda's params.
    scopes: Vec<HashSet<String>>,
    /// Python name -> the source name that claimed it, so two names never fold into one.
    owners: HashMap<String, String>,
    tmp: usize,
    /// J86: the multi-module context (other modules' exports, adapters, class methods).
    ctx: ModuleCtx,
    /// J86: source names of classes visible here (declared or imported) -> Python name.
    classes: HashMap<String, String>,
    /// J86: `from <module> import <names>` lines this module needs, by module.
    pub imports: BTreeMap<String, BTreeSet<String>>,
    /// J86: the class whose body is being lowered.
    class_ctx: Option<ClassCtx>,
    /// J86: index into `scopes` where each enclosing `def` starts, innermost last, with the names
    /// it must declare `nonlocal`.
    defs: Vec<(usize, BTreeSet<String>)>,
    /// J86: what an unlabelled `break` would leave, innermost last.
    breaks: Vec<BreakTarget>,
    /// J87: this round's assumptions (`types::Assume`), and what this round observed.
    assume: Assume,
    observed: Observed,
    /// J87: the owner (the span start of the function, arrow or method) of each scope in `scopes`.
    scope_owner: Vec<u32>,
    /// J87: lowering the typed body of a module function, so its locals are keyed apart from the
    /// guarded entry's untyped body.
    typed: bool,
    /// J87: the return key of each enclosing body, innermost last (None: a closure or a method).
    rets: Vec<Option<Key>>,
    /// J87: module functions (declarations and `const` arrows), by source name.
    sigs: HashMap<String, Sig>,
    /// J87: module-level `const` bindings of a value (not an arrow).
    module_consts: HashSet<String>,
    /// J87: non-exported module `const`s bound to an array literal: frozen unless a use escapes.
    frozen: HashSet<String>,
    /// J87: the module's interfaces and type aliases.
    types: TypeDecls,
    /// J87: the data fields a binding's annotation declares, by (scope owner, source name).
    declared: HashMap<(u32, String), BTreeSet<String>>,
    /// J87: the call being lowered is a whole expression statement.
    statement_call: bool,
    /// J87: frozen module constants bound to an object literal (read by member only).
    frozen_objects: HashSet<String>,
    /// J87: `const` bindings (never reassigned), which a guard may narrow.
    consts: HashSet<Key>,
    /// J87: narrowed facts in force, innermost last: (binding, what it is here).
    narrow: Vec<(Key, Fact)>,
    /// J87: the identifier being lowered is read where its value cannot escape (`peek`).
    peek_read: bool,
}

/// J87: a module function's signature, as the fixpoint and its call sites need it.
#[derive(Clone)]
struct Sig {
    /// The Python name (the guarded entry when the function is wrapped).
    py: String,
    /// The Python name of the typed body when the function is wrapped.
    typed_py: String,
    exported: bool,
    /// Per parameter: the fact its annotation proves inside the typed body (None: not guarded).
    params: Vec<Option<Fact>>,
}

impl Sig {
    fn typed(&self) -> bool {
        self.params.iter().any(Option::is_some)
    }
}

/// J87: which function body a lowering is emitting.
#[derive(Clone, Copy)]
enum FnSource<'b, 'a> {
    Decl(&'b Function<'a>),
    Arrow(&'b ArrowFunctionExpression<'a>),
}

impl<'s> Lowerer<'s> {
    pub fn new(src: &'s str) -> Self {
        Self::with_ctx(src, ModuleCtx::default())
    }

    pub fn with_ctx(src: &'s str, ctx: ModuleCtx) -> Self {
        Self::with_assume(src, ctx, Assume::default())
    }

    /// J87: one round of the fixpoint, under `assume` (`lib.rs` runs rounds until it is stable).
    pub fn with_assume(src: &'s str, ctx: ModuleCtx, assume: Assume) -> Self {
        Lowerer {
            src,
            refusals: Vec::new(),
            regexes: Vec::new(),
            globals: HashMap::new(),
            error_classes: HashSet::new(),
            adapter_fns: HashSet::new(),
            catch_params: Vec::new(),
            exports: Vec::new(),
            scopes: Vec::new(),
            owners: HashMap::new(),
            tmp: 0,
            ctx,
            classes: HashMap::new(),
            imports: BTreeMap::new(),
            class_ctx: None,
            defs: Vec::new(),
            breaks: Vec::new(),
            assume,
            observed: Observed::default(),
            scope_owner: Vec::new(),
            typed: false,
            rets: Vec::new(),
            sigs: HashMap::new(),
            module_consts: HashSet::new(),
            frozen: HashSet::new(),
            types: TypeDecls::default(),
            declared: HashMap::new(),
            statement_call: false,
            frozen_objects: HashSet::new(),
            consts: HashSet::new(),
            narrow: Vec::new(),
            peek_read: false,
        }
    }

    /// J87: the assumptions the next round runs under; equal to this round's at the fixpoint.
    pub fn next_assume(&self) -> Assume {
        self.observed.next(&self.assume)
    }

    /// J87: the assumptions this round ran under.
    pub fn assumed(&self) -> &Assume {
        &self.assume
    }

    fn push_scope(&mut self, locals: HashSet<String>, owner: u32) {
        self.scopes.push(locals);
        self.scope_owner.push(owner);
    }

    fn pop_scope(&mut self) {
        self.scopes.pop();
        self.scope_owner.pop();
    }

    /// J87: the key a binding's facts are kept under, if it is a local or a module value `const`.
    fn var_key(&self, name: &str) -> Option<Key> {
        if let Some(i) = self.scopes.iter().rposition(|s| s.contains(name)) {
            return Some(Key::Var {
                typed: self.typed,
                owner: self.scope_owner[i],
                name: name.to_string(),
            });
        }
        if self.module_consts.contains(name) {
            return Some(Key::Var {
                typed: false,
                owner: MODULE,
                name: name.to_string(),
            });
        }
        None
    }

    /// J87: what this round assumes for `key` (None: nothing yet, so anything), noting the read.
    fn lookup(&mut self, key: &Key) -> Option<Fact> {
        self.observed.read.insert(key.clone());
        self.assume.facts.get(key).cloned()
    }

    /// J87: `name` is bound to `value` (a declaration, an assignment, a loop or parameter binding).
    /// A binding keeps the flags only: its array may be mutated after this point.
    fn bind(&mut self, name: &str, fact: Fact) {
        if let Some(key) = self.var_key(name) {
            self.observed.observe(key, fact.shallow());
        }
    }

    /// J87: a parameter or declared local bound to `fact` (one binding per execution).
    fn bind_decl(&mut self, name: &str, fact: Fact) {
        if let Some(key) = self.var_key(name) {
            self.observed.declared.insert(key);
        }
        self.bind(name, fact);
    }

    /// J87: the Python name of the UTF-16 view of `name`, when that binding's view is hoisted
    /// (`types::Assume::hoist`): computed once beside the binding and indexed inline.
    fn units_of(&mut self, object: &Expression<'_>, proven_str: bool) -> Option<String> {
        if !proven_str {
            return None;
        }
        let Expression::Identifier(id) = strip_parens(object) else {
            return None;
        };
        if !self.is_scoped(id.name.as_str()) {
            return None;
        }
        let key = self.var_key(id.name.as_str())?;
        self.observed.unit_reads.insert(key.clone());
        self.assume
            .hoist
            .contains(&key)
            .then(|| units_name(id.name.as_str()))
    }

    /// J87: `_jsu_<name> = _js_code_units(<name>)` after a binding whose view is hoisted.
    fn hoist_line(&mut self, name: &str, indent: usize, out: &mut Vec<String>) {
        if let Some(key) = self.var_key(name)
            && self.assume.hoist.contains(&key)
        {
            out.push(format!(
                "{}{} = _js_code_units({})",
                pad(indent),
                units_name(name),
                py_name(name, false, false)
            ));
        }
    }

    /// J87: the facts of a local or module `const` applied to its lowered read.
    fn with_binding_facts(&mut self, name: &str, py: Py) -> Py {
        match self.var_key(name) {
            Some(key) => {
                let fact = self.lookup(&key);
                if let Some((_, narrowed)) = self.narrow.iter().rev().find(|(k, _)| *k == key) {
                    let narrowed = narrowed.clone();
                    return py.with_fact(Some(&narrowed));
                }
                py.with_fact(fact.as_ref())
            }
            None => py,
        }
    }

    /// J87: a `const` binding (local or module) named by `e`, which a guard may narrow.
    fn narrowable(&self, e: &Expression<'_>) -> Option<Key> {
        let Expression::Identifier(id) = strip_parens(e) else {
            return None;
        };
        let key = self.var_key(id.name.as_str())?;
        let module = matches!(key, Key::Var { owner: MODULE, .. });
        (module || self.consts.contains(&key)).then_some(key)
    }

    /// J87: the current fact of a binding (a narrowing in force, else this round's assumption).
    fn current(&mut self, key: &Key) -> Option<Fact> {
        match self.narrow.iter().rev().find(|(k, _)| k == key) {
            Some((_, f)) => Some(f.clone()),
            None => self.lookup(key),
        }
    }

    /// J87: what `test` being `when` proves about `const` bindings, each as the fact it narrows
    /// the binding to there (SUBSET.md, Types: narrowing).
    fn narrowings(&mut self, test: &Expression<'_>, when: bool) -> Vec<(Key, Fact)> {
        use BinaryOperator as Op;
        match strip_parens(test) {
            Expression::LogicalExpression(l) => match (l.operator, when) {
                // Both hold.
                (LogicalOperator::And, true) | (LogicalOperator::Or, false) => {
                    let mut out = self.narrowings(&l.left, when);
                    out.extend(self.narrowings(&l.right, when));
                    out
                }
                // One of the two holds: what both sides prove of the same binding.
                (LogicalOperator::Or, true) | (LogicalOperator::And, false) => {
                    let left = self.narrowings(&l.left, when);
                    let right = self.narrowings(&l.right, when);
                    left.into_iter()
                        .filter_map(|(key, a)| {
                            right
                                .iter()
                                .find(|(k, _)| *k == key)
                                .map(|(_, b)| (key.clone(), a.meet_core_pub(b)))
                        })
                        .collect()
                }
                _ => Vec::new(),
            },
            Expression::UnaryExpression(u) if u.operator == UnaryOperator::LogicalNot => {
                // `!x` false: x is truthy, so neither null nor undefined.
                if !when && let Some(key) = self.narrowable(&u.argument) {
                    return self
                        .defined_narrowing(key, true, true)
                        .into_iter()
                        .collect();
                }
                self.narrowings(&u.argument, !when)
            }
            Expression::Identifier(_) if when => match self.narrowable(test) {
                Some(key) => self
                    .defined_narrowing(key, true, true)
                    .into_iter()
                    .collect(),
                None => Vec::new(),
            },
            Expression::BinaryExpression(b) => {
                let (eq, strict) = match b.operator {
                    Op::StrictEquality => (true, true),
                    Op::StrictInequality => (false, true),
                    Op::Equality => (true, false),
                    Op::Inequality => (false, false),
                    _ => return Vec::new(),
                };
                // The test is true exactly when the two sides are equal (`eq`) or unequal.
                let equal = eq == when;
                // `x === null` / `x == undefined` ...: rules out what it names when unequal.
                for (side, other) in [(&b.left, &b.right), (&b.right, &b.left)] {
                    if !is_nullish_literal(other) {
                        continue;
                    }
                    if matches!(strip_parens(other), Expression::Identifier(_))
                        && self.is_local("undefined")
                    {
                        return Vec::new();
                    }
                    let Some(key) = self.narrowable(side) else {
                        return Vec::new();
                    };
                    if equal {
                        return Vec::new();
                    }
                    let null_lit = matches!(strip_parens(other), Expression::NullLiteral(_));
                    let (no_null, no_undef) = if strict {
                        (null_lit, !null_lit)
                    } else {
                        (true, true)
                    };
                    return self
                        .defined_narrowing(key, no_null, no_undef)
                        .into_iter()
                        .collect();
                }
                if !strict || !equal {
                    return Vec::new();
                }
                // `x === 'lit'` / `typeof x === 'string'` true: what x must then be.
                for (side, other) in [(&b.left, &b.right), (&b.right, &b.left)] {
                    // (Not a number literal: `===` compares numbers as doubles, so an int past
                    // 2^53 can equal one and is not what `num` promises.)
                    let literal = match strip_parens(other) {
                        Expression::StringLiteral(_) => Some(Fact::str_()),
                        _ => None,
                    };
                    if let (Some(fact), Some(key)) = (literal.clone(), self.narrowable(side)) {
                        return vec![(key, fact)];
                    }
                    if let (Expression::UnaryExpression(u), Expression::StringLiteral(s)) =
                        (strip_parens(side), strip_parens(other))
                        && u.operator == UnaryOperator::Typeof
                        && let Some(key) = self.narrowable(&u.argument)
                    {
                        let fact = match s.value.as_str() {
                            Some("string") => Fact::str_(),
                            Some("boolean") => Fact::bool_(),
                            _ => continue,
                        };
                        return vec![(key, fact)];
                    }
                }
                Vec::new()
            }
            _ => Vec::new(),
        }
    }

    /// J87: a binding with the nullish values ruled out (by the test, or because it never holds
    /// the other one) is what its fact says it is when defined.
    fn defined_narrowing(
        &mut self,
        key: Key,
        no_null: bool,
        no_undef: bool,
    ) -> Option<(Key, Fact)> {
        let base = self.current(&key)?;
        let ruled = (no_null || base.never_null()) && (no_undef || base.never_undef());
        let defined = base.defined().filter(|_| ruled)?;
        Some((key, defined))
    }

    /// J87: narrow where `test` is known to be `when`. The binding's own fact already holds only
    /// what it may keep (`bind`, held consts), so a narrowing keeps all of what it proves.
    fn narrow_on(&mut self, test: &Expression<'_>, when: bool) {
        for (key, fact) in self.narrowings(test, when) {
            self.narrow.push((key, fact));
        }
    }

    /// J87: record a binding's annotated data fields (SUBSET.md, *A data field read as data*).
    fn declare_annotation(&mut self, name: &str, annotation: Option<&TSTypeAnnotation<'_>>) {
        let Some(annotation) = annotation else { return };
        let Some(fields) = self.types.annotation_fields(&annotation.type_annotation) else {
            return;
        };
        let owner = match self.scopes.iter().rposition(|s| s.contains(name)) {
            Some(i) => self.scope_owner[i],
            None => MODULE,
        };
        self.declared.insert((owner, name.to_string()), fields);
    }

    /// J87: the receiver's declared type proves `name` is a data field, not a method.
    fn declared_data(&self, object: &Expression<'_>, name: &str) -> bool {
        let Expression::Identifier(id) = strip_parens(object) else {
            return false;
        };
        let owner = match self
            .scopes
            .iter()
            .rposition(|s| s.contains(id.name.as_str()))
        {
            Some(i) => self.scope_owner[i],
            None if self.globals.contains_key(id.name.as_str()) => MODULE,
            None => return false,
        };
        self.declared
            .get(&(owner, id.name.to_string()))
            .is_some_and(|fields| fields.contains(name))
    }

    fn refuse(&mut self, span: Span, construct: impl Into<String>) -> Py {
        self.refusals.push(Refusal {
            span,
            construct: construct.into(),
        });
        Py {
            pure: true,
            ..Py::atom("None")
        }
    }

    fn text(&self, span: Span) -> &'s str {
        &self.src[span.start as usize..span.end as usize]
    }

    /// Record that `src` is spelled `py`, refusing a reserved prefix or a fold of two names.
    fn claim(&mut self, src: &str, py: &str, span: Span) {
        if src.starts_with("_js") || src.starts_with("_Js") || src.starts_with("_JS") {
            self.refuse(span, "identifier with the reserved _js prefix");
            return;
        }
        match self.owners.get(py) {
            Some(owner) if owner != src => {
                let construct = format!("name collision ({owner} and {src} both lower to {py})");
                self.refuse(span, construct);
            }
            Some(_) => {}
            None => {
                self.owners.insert(py.to_string(), src.to_string());
            }
        }
    }

    // ---------------------------------------------------------------- module

    /// Lower a whole program to the module body (everything below `__all__`).
    pub fn program(&mut self, program: &Program<'_>) -> String {
        // J87: the module's named types, and every name an `export { ... }` list exports.
        self.types = TypeDecls::read(program);
        let mut listed: HashSet<String> = HashSet::new();
        for stmt in &program.body {
            if let Statement::ExportNamedDeclaration(e) = stmt {
                for specifier in &e.specifiers {
                    listed.insert(specifier.local.name().to_string());
                }
            }
        }
        // Pass 1: module-level names, so a function may call one declared below it.
        for stmt in &program.body {
            if let Statement::ImportDeclaration(i) = stmt {
                self.import(i);
                continue;
            }
            let (decl, exported) = match stmt {
                Statement::ExportDeclaration(e) => (Some(&e.declaration), true),
                _ => (stmt.as_declaration(), false),
            };
            let Some(decl) = decl else { continue };
            match decl {
                Declaration::ClassDeclaration(c) => {
                    if let Some(id) = &c.id {
                        let py = class_py_name(id.name.as_str(), exported);
                        if is_py_keyword(&py) {
                            self.refuse(id.span, "class name that is a Python keyword");
                        }
                        self.claim(id.name.as_str(), &py, id.span);
                        if exported {
                            self.exports.push(py.clone());
                        }
                        self.globals.insert(id.name.to_string(), py.clone());
                        self.classes.insert(id.name.to_string(), py);
                    }
                }
                Declaration::FunctionDeclaration(f) => {
                    if let Some(id) = &f.id {
                        self.declare_global(id.name.as_str(), exported, id.span);
                        let public = exported || listed.contains(id.name.as_str());
                        self.add_sig(id.name.as_str(), public, &f.params, id.span);
                    }
                }
                Declaration::VariableDeclaration(v) => {
                    for d in &v.declarations {
                        if let BindingPattern::BindingIdentifier(id) = &d.id {
                            self.declare_global(id.name.as_str(), exported, id.span);
                            let public = exported || listed.contains(id.name.as_str());
                            match &d.init {
                                Some(Expression::ArrowFunctionExpression(a)) => {
                                    self.add_sig(id.name.as_str(), public, &a.params, id.span);
                                }
                                init => {
                                    if v.kind == VariableDeclarationKind::Const {
                                        self.module_consts.insert(id.name.to_string());
                                        if !public
                                            && matches!(init, Some(Expression::ArrayExpression(_)))
                                        {
                                            self.frozen.insert(id.name.to_string());
                                        }
                                        if !public
                                            && matches!(init, Some(Expression::ObjectExpression(_)))
                                        {
                                            self.frozen.insert(id.name.to_string());
                                            self.frozen_objects.insert(id.name.to_string());
                                        }
                                        self.declare_annotation(
                                            id.name.as_str(),
                                            d.type_annotation.as_deref(),
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
                _ => {}
            }
        }

        let mut items: Vec<Vec<String>> = Vec::new();
        for stmt in &program.body {
            let mut out = Vec::new();
            self.top_level(stmt, &mut out);
            if !out.is_empty() {
                items.push(out);
            }
        }

        let mut body = String::new();
        if !self.regexes.is_empty() {
            for (i, (pattern, global)) in self.regexes.iter().enumerate() {
                let compiled = format!("_js_re.compile({}, _js_re.ASCII)", py_str(pattern));
                if *global {
                    body.push_str(&format!("_JS_RE_{i} = _JsGlobalRegExp({compiled})\n"));
                } else {
                    body.push_str(&format!("_JS_RE_{i} = {compiled}\n"));
                }
            }
            body.push_str("\n\n");
        }
        let blocks: Vec<String> = items.iter().map(|lines| lines.join("\n") + "\n").collect();
        body.push_str(&blocks.join("\n\n"));
        body
    }

    fn declare_global(&mut self, name: &str, exported: bool, span: Span) {
        let py = py_name(name, true, !exported);
        self.claim(name, &py, span);
        if exported {
            self.exports.push(py.clone());
        }
        self.globals.insert(name.to_string(), py);
    }

    fn top_level(&mut self, stmt: &Statement<'_>, out: &mut Vec<String>) {
        match stmt {
            Statement::ExportDeclaration(e) => self.top_declaration(&e.declaration, out),
            Statement::ExportNamedDeclaration(e) => {
                if !e.export_kind.is_type() {
                    self.export_list(e);
                }
            }
            Statement::ExportFromDeclaration(e) => {
                if !e.export_kind.is_type() {
                    self.refuse(e.span, "re-export");
                }
            }
            // Resolved in pass 1 (`import`), through a compiled module or the adapter seam.
            Statement::ImportDeclaration(_) => {}
            Statement::EmptyStatement(_) => {}
            _ => match stmt.as_declaration() {
                Some(decl) => self.top_declaration(decl, out),
                None => {
                    self.refuse(stmt.span(), statement_kind(stmt));
                }
            },
        }
    }

    fn top_declaration(&mut self, decl: &Declaration<'_>, out: &mut Vec<String>) {
        match decl {
            Declaration::TSTypeAliasDeclaration(_) | Declaration::TSInterfaceDeclaration(_) => {}
            Declaration::FunctionDeclaration(f) => {
                let Some(id) = &f.id else {
                    self.refuse(f.span, "anonymous function");
                    return;
                };
                match &f.body {
                    Some(_) => self.module_function(id.name.as_str(), FnSource::Decl(f), out),
                    None => {
                        self.refuse(f.span, "function overload signature");
                    }
                }
            }
            Declaration::VariableDeclaration(v) => {
                if v.kind != VariableDeclarationKind::Const {
                    self.refuse(v.span, "module-level let/var");
                    return;
                }
                for d in &v.declarations {
                    let BindingPattern::BindingIdentifier(id) = &d.id else {
                        self.refuse(d.span, "destructuring declaration");
                        continue;
                    };
                    let name = self.globals[id.name.as_str()].clone();
                    match &d.init {
                        Some(Expression::ArrowFunctionExpression(a)) => {
                            self.module_function(id.name.as_str(), FnSource::Arrow(a), out);
                        }
                        Some(init) => {
                            let value = self.expr(init);
                            out.push(format!("{name} = {}", value.code));
                            // J87: a frozen array keeps what its elements are; any other const
                            // keeps the flags of its value (the binding never changes).
                            let source = id.name.as_str();
                            let frozen = self.frozen.contains(source)
                                && !self.assume.escaped.contains(source);
                            let fact = value.fact();
                            let fact = if frozen {
                                Fact {
                                    tuple: None,
                                    ..fact
                                }
                            } else {
                                fact.shallow()
                            };
                            self.observed.observe(
                                Key::Var {
                                    typed: false,
                                    owner: MODULE,
                                    name: source.to_string(),
                                },
                                fact,
                            );
                        }
                        None => {
                            self.refuse(d.span, "const without initializer");
                        }
                    }
                }
            }
            Declaration::ClassDeclaration(c) => self.class_decl(c, out),
            Declaration::TSEnumDeclaration(e) => {
                self.refuse(e.span, "enum");
            }
            other => {
                self.refuse(other.span(), "declaration");
            }
        }
    }

    // ---------------------------------------------------------------- functions

    /// J87: record a module function's signature; one whose parameters carry a provable annotation
    /// gets a typed body (and, when wrapped, a guarded entry under its own name).
    fn add_sig(&mut self, name: &str, exported: bool, params: &FormalParameters<'_>, span: Span) {
        let py = self.globals[name].clone();
        let facts: Vec<Option<Fact>> = params
            .items
            .iter()
            .map(|p| {
                if p.optional
                    || p.initializer.is_some()
                    || !matches!(p.pattern, BindingPattern::BindingIdentifier(_))
                {
                    return None;
                }
                p.type_annotation
                    .as_ref()
                    .and_then(|a| self.types.param_fact(&a.type_annotation))
            })
            .collect();
        let sig = Sig {
            typed_py: format!("_{}__typed", py.trim_start_matches('_')),
            py,
            exported,
            params: facts,
        };
        if sig.typed() {
            if exported {
                self.observed.wrapped.insert(name.to_string());
            }
            if exported || self.assume.wrapped.contains(name) {
                let owner = format!("{name} (its typed body)");
                self.claim(&owner, &sig.typed_py.clone(), span);
            }
        }
        self.sigs.insert(name.to_string(), sig);
    }

    fn is_wrapped(&self, name: &str) -> bool {
        self.sigs
            .get(name)
            .is_some_and(|sig| sig.typed() && (sig.exported || self.assume.wrapped.contains(name)))
    }

    /// A module function: one body, or (J87) a typed body whose parameters hold what their
    /// annotations say, plus, when anything may call it with an unproven argument, a guarded entry
    /// under the function's own name that checks the arguments and runs the typed body or the
    /// untyped one (SUBSET.md, Types).
    fn module_function(&mut self, src: &str, source: FnSource<'_, '_>, out: &mut Vec<String>) {
        let sig = self.sigs[src].clone();
        let ret = |typed: bool| Key::Ret {
            name: src.to_string(),
            typed,
        };
        if !sig.typed() {
            self.typed = false;
            self.function_body(&sig.py, source, &[], None, ret(false), out);
            return;
        }
        let wrapped = self.is_wrapped(src);
        let typed_name = if wrapped {
            sig.typed_py.clone()
        } else {
            sig.py.clone()
        };
        self.typed = true;
        self.function_body(&typed_name, source, &sig.params, None, ret(true), out);
        if wrapped {
            out.push(String::new());
            out.push(String::new());
            self.typed = false;
            let guard = (sig.typed_py.as_str(), sig.params.as_slice());
            self.function_body(&sig.py, source, &[], Some(guard), ret(false), out);
        }
        self.typed = false;
    }

    fn function_body(
        &mut self,
        name: &str,
        source: FnSource<'_, '_>,
        facts: &[Option<Fact>],
        guard: Option<(&str, &[Option<Fact>])>,
        ret: Key,
        out: &mut Vec<String>,
    ) {
        let (params, owner, statements) = match source {
            FnSource::Decl(f) => {
                if f.generator {
                    self.refuse(f.span, "generator function");
                }
                if f.r#async {
                    self.refuse(f.span, "async function");
                }
                let body = f.body.as_ref().map(|b| b.statements.as_slice());
                (&f.params, f.span.start, body)
            }
            FnSource::Arrow(a) => {
                if a.r#async {
                    self.refuse(a.span, "async function");
                }
                let body = match &a.body {
                    ArrowFunctionBody::FunctionBody(b) => Some(b.statements.as_slice()),
                    _ => None,
                };
                (&a.params, a.span.start, body)
            }
        };
        let names = self.params(params);
        let mut locals: HashSet<String> = names.iter().map(|(src, _)| src.clone()).collect();
        if let Some(statements) = statements {
            let mut stack = vec![locals.clone()];
            self.collect_block(statements, &mut stack, &mut locals);
        }
        self.push_scope(locals, owner);
        self.rets.push(Some(ret.clone()));
        self.bind_params(params, facts);
        out.push(format!("def {name}({}):", join_params(&names)));
        if let Some((typed, admitted)) = guard {
            let bare: Vec<&str> = names
                .iter()
                .map(|(_, py)| py.split('=').next().unwrap_or(py))
                .collect();
            let tests: Vec<String> = admitted
                .iter()
                .zip(&bare)
                .filter_map(|(fact, name)| fact.as_ref().map(|f| types::guard_test(f, name)))
                .collect();
            out.push(format!("    if {}:", tests.join(" and ")));
            out.push(format!("        return {typed}({})", bare.join(", ")));
        }
        self.param_defaults(params, 1, out);
        self.hoist_params(params, 1, out);
        match (source, statements) {
            (_, Some(statements)) => {
                self.block(statements, 1, out);
                // J86: a body that can run off its end returns `undefined`, as JS does (Python:
                // `None`).
                if !ends_in_exit(statements) {
                    out.push("    return _JS_UNDEFINED".to_string());
                }
                if types::completes(statements) {
                    self.observed.observe(ret, Fact::default());
                }
            }
            (FnSource::Arrow(a), None) => {
                let expr = a
                    .body
                    .as_expression()
                    .expect("an arrow body is a block or an expression");
                let value = self.expr(expr);
                out.push(format!("    return {}", value.code));
                self.observed.observe(ret, value.fact());
            }
            (FnSource::Decl(_), None) => {}
        }
        self.rets.pop();
        self.pop_scope();
    }

    /// J87: bind each parameter to what the body may assume of it: its annotation's fact in the
    /// typed body, nothing anywhere else.
    fn bind_params(&mut self, params: &FormalParameters<'_>, facts: &[Option<Fact>]) {
        for (i, p) in params.items.iter().enumerate() {
            if let BindingPattern::BindingIdentifier(id) = &p.pattern {
                let fact = facts.get(i).cloned().flatten().unwrap_or_default();
                self.bind_decl(id.name.as_str(), fact);
                self.declare_annotation(id.name.as_str(), p.type_annotation.as_deref());
            }
        }
    }

    /// J87: the hoisted UTF-16 views of the parameters, at the top of a body.
    fn hoist_params(
        &mut self,
        params: &FormalParameters<'_>,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        for p in &params.items {
            if let BindingPattern::BindingIdentifier(id) = &p.pattern {
                self.hoist_line(id.name.as_str(), indent, out);
            }
        }
    }

    /// J87: a `return` of `fact` from the innermost body that records its returns.
    fn observe_return(&mut self, fact: Fact) {
        if let Some(Some(key)) = self.rets.last().cloned() {
            self.observed.observe(key, fact);
        }
    }

    /// `if p is _JS_UNDEFINED: p = <default>` for each defaulted parameter, in order: JS applies a
    /// default when the argument is missing or `undefined`, evaluated at call time (J86).
    fn param_defaults(
        &mut self,
        params: &FormalParameters<'_>,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        for p in &params.items {
            let (Some(init), BindingPattern::BindingIdentifier(id)) = (&p.initializer, &p.pattern)
            else {
                continue;
            };
            let name = py_name(id.name.as_str(), false, false);
            let value = self.expr(init);
            out.push(format!("{}if {name} is _JS_UNDEFINED:", pad(indent)));
            out.push(format!("{}{name} = {}", pad(indent + 1), value.code));
        }
    }

    /// Parameter list: `(source name, python spelling)`. An optional parameter defaults to
    /// `undefined`, which is what JS passes for a missing argument.
    fn params(&mut self, params: &FormalParameters<'_>) -> Vec<(String, String)> {
        let mut names = Vec::new();
        for p in &params.items {
            let BindingPattern::BindingIdentifier(id) = &p.pattern else {
                self.refuse(p.span, "destructuring parameter");
                continue;
            };
            let py = py_name(id.name.as_str(), false, false);
            self.claim(id.name.as_str(), &py, id.span);
            let spelled = if p.optional || p.initializer.is_some() {
                format!("{py}=_JS_UNDEFINED")
            } else {
                py
            };
            names.push((id.name.to_string(), spelled));
        }
        if let Some(rest) = &params.rest {
            self.refuse(rest.span, "rest parameter");
        }
        names
    }

    // ---------------------------------------------------------------- binding analysis

    fn collect_block(
        &mut self,
        stmts: &[Statement<'_>],
        stack: &mut Vec<HashSet<String>>,
        all: &mut HashSet<String>,
    ) {
        stack.push(HashSet::new());
        for s in stmts {
            self.collect_stmt(s, stack, all);
        }
        stack.pop();
    }

    fn collect_nested(
        &mut self,
        s: &Statement<'_>,
        stack: &mut Vec<HashSet<String>>,
        all: &mut HashSet<String>,
    ) {
        match s {
            Statement::BlockStatement(b) => self.collect_block(&b.body, stack, all),
            other => self.collect_block(std::slice::from_ref(other), stack, all),
        }
    }

    fn collect_stmt(
        &mut self,
        s: &Statement<'_>,
        stack: &mut Vec<HashSet<String>>,
        all: &mut HashSet<String>,
    ) {
        match s {
            Statement::VariableDeclaration(v) => {
                for d in &v.declarations {
                    self.declare_pattern(&d.id, stack, all);
                }
            }
            Statement::BlockStatement(b) => self.collect_block(&b.body, stack, all),
            Statement::IfStatement(i) => {
                self.collect_nested(&i.consequent, stack, all);
                if let Some(alt) = &i.alternate {
                    self.collect_nested(alt, stack, all);
                }
            }
            Statement::WhileStatement(w) => self.collect_nested(&w.body, stack, all),
            Statement::ForStatement(f) => {
                stack.push(HashSet::new());
                if let Some(ForStatementInit::VariableDeclaration(v)) = &f.init {
                    for d in &v.declarations {
                        self.declare_pattern(&d.id, stack, all);
                    }
                }
                self.collect_nested(&f.body, stack, all);
                stack.pop();
            }
            Statement::TryStatement(t) => {
                self.collect_block(&t.block.body, stack, all);
                if let Some(handler) = &t.handler {
                    self.collect_block(&handler.body.body, stack, all);
                }
                if let Some(finalizer) = &t.finalizer {
                    self.collect_block(&finalizer.body, stack, all);
                }
            }
            // A switch body is one block scope, whatever case a declaration sits under.
            Statement::SwitchStatement(sw) => {
                stack.push(HashSet::new());
                for case in &sw.cases {
                    for s in &case.consequent {
                        self.collect_stmt(s, stack, all);
                    }
                }
                stack.pop();
            }
            Statement::LabeledStatement(l) => self.collect_nested(&l.body, stack, all),
            Statement::ForOfStatement(f) => {
                stack.push(HashSet::new());
                if let ForStatementLeft::VariableDeclaration(v) = &f.left {
                    for d in &v.declarations {
                        self.declare_pattern(&d.id, stack, all);
                    }
                }
                self.collect_nested(&f.body, stack, all);
                stack.pop();
            }
            _ => {}
        }
    }

    fn declare_pattern(
        &mut self,
        pattern: &BindingPattern<'_>,
        stack: &mut [HashSet<String>],
        all: &mut HashSet<String>,
    ) {
        match pattern {
            BindingPattern::BindingIdentifier(id) => {
                let name = id.name.to_string();
                if stack.iter().any(|block| block.contains(&name)) {
                    self.refuse(id.span, "shadowed binding");
                    return;
                }
                if self.globals.contains_key(&name) {
                    self.refuse(id.span, "local binding that shadows a module-level name");
                    return;
                }
                let py = py_name(&name, false, false);
                self.claim(&name, &py, id.span);
                stack
                    .last_mut()
                    .expect("a block is open")
                    .insert(name.clone());
                all.insert(name);
            }
            BindingPattern::ArrayPattern(a) => {
                for element in a.elements.iter().flatten() {
                    self.declare_pattern(element, stack, all);
                }
            }
            BindingPattern::ObjectPattern(o) => {
                for property in &o.properties {
                    self.declare_pattern(&property.value, stack, all);
                }
            }
            // Refused where the declaration is lowered.
            _ => {}
        }
    }

    fn resolve(&mut self, name: &str, span: Span) -> Py {
        let peeked = std::mem::take(&mut self.peek_read);
        // J87-3: what a `catch` binding holds may be a Python exception (an adapter's OSError),
        // whose properties JS would read differently; only rethrowing it is accepted.
        if self.catch_params.iter().any(|(n, _)| n == name) {
            return self.refuse(span, "use of a catch binding other than rethrowing it");
        }
        if self.scopes.iter().rev().any(|scope| scope.contains(name)) {
            // J87: a `const` read anywhere its value can escape keeps no array contents.
            if !peeked
                && let Some(key) = self.var_key(name)
                && self.consts.contains(&key)
            {
                self.observed.escaped_locals.insert(key);
            }
            let read = Py {
                pure: true,
                ..Py::atom(py_name(name, false, false))
            };
            return self.with_binding_facts(name, read);
        }
        if self.globals.contains_key(name) {
            return self.global_read(name, span, true);
        }
        if name == "undefined" {
            return Py {
                pure: true,
                is_undef: true,
                ..Py::atom("_JS_UNDEFINED")
            };
        }
        // J86: the two non-finite number globals.
        if name == "Infinity" || name == "NaN" {
            return Py {
                pure: true,
                is_num: true,
                is_double: true,
                ..Py::atom(if name == "NaN" {
                    "_JS_NAN"
                } else {
                    "_JS_INFINITY"
                })
            };
        }
        let construct = format!("global {name}");
        self.refuse(span, construct)
    }

    /// A module-level name read as a value. J87: a module function read anywhere but as a direct
    /// callee needs its guarded entry; a frozen array read anywhere but a destructuring `for-of`
    /// escapes; a module value `const` carries what its initializer proved.
    fn global_read(&mut self, name: &str, _span: Span, escapes: bool) -> Py {
        let py = self.globals[name].clone();
        if self.sigs.get(name).is_some_and(Sig::typed) {
            self.observed.wrapped.insert(name.to_string());
        }
        if escapes && self.frozen.contains(name) {
            self.observed.escaped.insert(name.to_string());
        }
        let read = Py {
            pure: true,
            ..Py::atom(py)
        };
        self.with_binding_facts(name, read)
    }

    /// J87: lower `e`, a read whose value cannot escape when `e` is a local: the object of a
    /// literal index, the operand of a nullish or truthiness test.
    fn peek(&mut self, e: &Expression<'_>) -> Py {
        if let Expression::Identifier(id) = strip_parens(e)
            && self.is_scoped(id.name.as_str())
        {
            self.peek_read = true;
        }
        let value = self.expr(e);
        self.peek_read = false;
        value
    }

    /// J87: the object of a member read. A frozen module object read here does not escape.
    fn member_object(&mut self, object: &Expression<'_>) -> Py {
        if let Expression::Identifier(id) = strip_parens(object)
            && self.frozen.contains(id.name.as_str())
            && !self.is_scoped(id.name.as_str())
            && self.frozen_objects.contains(id.name.as_str())
        {
            return self.global_read(id.name.as_str(), id.span, false);
        }
        self.expr(object)
    }

    /// J87: a property of a frozen module object is one of its literal values, or `undefined`.
    fn frozen_member(&self, object: &Py, read: Py) -> Py {
        match &object.elem {
            Some(value) if !object.is_list && !object.top => Py {
                nn: Some(Box::new(value.shallow())),
                no_null: value.never_null(),
                ..read
            },
            _ => read,
        }
    }

    fn is_scoped(&self, name: &str) -> bool {
        self.scopes.iter().any(|scope| scope.contains(name))
    }

    fn is_local(&self, name: &str) -> bool {
        self.scopes.iter().any(|scope| scope.contains(name)) || self.globals.contains_key(name)
    }

    // ---------------------------------------------------------------- statements

    fn block(&mut self, stmts: &[Statement<'_>], indent: usize, out: &mut Vec<String>) {
        let mark = self.narrow.len();
        for s in stmts {
            self.stmt(s, indent, out);
            // J87: after `if (<test>) <exits>`, the rest of the block runs only when the test
            // was false.
            if let Statement::IfStatement(i) = s
                && i.alternate.is_none()
                && exits(&i.consequent)
            {
                self.narrow_on(&i.test, false);
            }
        }
        self.narrow.truncate(mark);
    }

    /// A nested body: always at least one line.
    fn body(&mut self, s: &Statement<'_>, indent: usize, out: &mut Vec<String>) {
        let start = out.len();
        match s {
            Statement::BlockStatement(b) => self.block(&b.body, indent, out),
            other => self.stmt(other, indent, out),
        }
        if out.len() == start {
            out.push(format!("{}pass", pad(indent)));
        }
    }

    fn stmt(&mut self, s: &Statement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        match s {
            Statement::ExpressionStatement(e) => match &e.expression {
                Expression::AssignmentExpression(a) => self.assignment(a, indent, out),
                Expression::UpdateExpression(u) => {
                    self.refuse(u.span, "update expression (++/--)");
                }
                other => {
                    self.statement_call = matches!(other, Expression::CallExpression(_));
                    let value = self.expr(other);
                    self.statement_call = false;
                    out.push(format!("{p}{}", value.code));
                }
            },
            Statement::VariableDeclaration(v) => self.var_decl(v, indent, out),
            Statement::ReturnStatement(r) => match &r.argument {
                Some(arg) => {
                    let value = self.expr(arg);
                    self.observe_return(value.fact());
                    out.push(format!("{p}return {}", value.code));
                }
                None => {
                    self.observe_return(Fact::default());
                    out.push(format!("{p}return _JS_UNDEFINED"));
                }
            },
            Statement::IfStatement(i) => {
                let test = self.condition(&i.test);
                out.push(format!("{p}if {test}:"));
                // J87: the consequent runs only when the test was true.
                let mark = self.narrow.len();
                self.narrow_on(&i.test, true);
                self.body(&i.consequent, indent + 1, out);
                self.narrow.truncate(mark);
                if let Some(alt) = &i.alternate
                    && !matches!(alt, Statement::IfStatement(_))
                {
                    out.push(format!("{p}else:"));
                    self.narrow_on(&i.test, false);
                    self.body(alt, indent + 1, out);
                    self.narrow.truncate(mark);
                    return;
                }
                let mut alternate = i.alternate.as_ref();
                while let Some(alt) = alternate {
                    if let Statement::IfStatement(next) = alt {
                        let test = self.condition(&next.test);
                        out.push(format!("{p}elif {test}:"));
                        self.body(&next.consequent, indent + 1, out);
                        alternate = next.alternate.as_ref();
                    } else {
                        out.push(format!("{p}else:"));
                        self.body(alt, indent + 1, out);
                        alternate = None;
                    }
                }
            }
            Statement::WhileStatement(w) => {
                let test = self.condition(&w.test);
                out.push(format!("{p}while {test}:"));
                self.breaks.push(BreakTarget::Loop);
                self.body(&w.body, indent + 1, out);
                self.breaks.pop();
            }
            // J86: `for (;;)` only; a C-style loop with a clause stays refused.
            Statement::ForStatement(f)
                if f.init.is_none() && f.test.is_none() && f.update.is_none() =>
            {
                out.push(format!("{p}while True:"));
                self.breaks.push(BreakTarget::Loop);
                self.body(&f.body, indent + 1, out);
                self.breaks.pop();
            }
            // J87-3: a C-style loop with a `let` init, a test and an assignment update.
            Statement::ForStatement(f) => self.c_for(f, indent, out),
            Statement::TryStatement(t) => self.try_stmt(t, indent, out),
            Statement::SwitchStatement(sw) => self.switch(sw, indent, out),
            // J87-3: `throw e` inside `catch (e)` rethrows what was caught, as it is.
            Statement::ThrowStatement(t)
                if matches!(strip(&t.argument), Expression::Identifier(id)
                    if self.catch_params.iter().any(|(name, _)| name == id.name.as_str())) =>
            {
                let Expression::Identifier(id) = strip(&t.argument) else {
                    unreachable!("matched above")
                };
                let caught = self
                    .catch_params
                    .iter()
                    .rev()
                    .find(|(name, _)| name == id.name.as_str())
                    .map(|(_, tmp)| tmp.clone())
                    .expect("matched above");
                out.push(format!("{p}raise {caught}"));
            }
            Statement::ThrowStatement(t) => {
                let value = self.expr(&t.argument);
                if self.is_error_construction(&t.argument) {
                    out.push(format!("{p}raise {}", value.code));
                } else {
                    out.push(format!("{p}raise _js_throw({})", value.code));
                }
            }
            Statement::ForOfStatement(f) => self.for_of(f, indent, out),
            Statement::BlockStatement(b) => self.block(&b.body, indent, out),
            Statement::BreakStatement(b) => {
                if b.label.is_some() {
                    self.refuse(b.span, "labelled break");
                } else if self.breaks.last() == Some(&BreakTarget::Switch) {
                    self.refuse(b.span, "break that does not end its switch case");
                } else {
                    out.push(format!("{p}break"));
                }
            }
            Statement::ContinueStatement(c) => {
                if c.label.is_some() {
                    self.refuse(c.span, "labelled continue");
                } else {
                    out.push(format!("{p}continue"));
                }
            }
            Statement::EmptyStatement(_) => {}
            Statement::TSTypeAliasDeclaration(_) | Statement::TSInterfaceDeclaration(_) => {}
            Statement::FunctionDeclaration(f) => {
                self.refuse(f.span, "nested function declaration");
            }
            Statement::LabeledStatement(l) => {
                // Refused, but its body is still walked so a `break label` inside is named too.
                self.refuse(l.span, "labelled statement");
                self.body(&l.body, indent, &mut Vec::new());
            }
            other => {
                self.refuse(other.span(), statement_kind(other));
            }
        }
    }

    /// J87-3: `for (let i = a; test; i -= 1) body` -> `i = a` / `while test:` / body / update. The
    /// init must be a `let` declaration (or absent), the update an assignment (or absent). A
    /// `continue` that would leave the body is refused: in JS it runs the update, and a Python
    /// `continue` would skip it. Closures in the body are refused as in any loop.
    fn c_for(&mut self, f: &ForStatement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        if f.init.is_none() && f.test.is_none() && f.update.is_none() {
            out.push(format!("{p}while True:"));
            self.breaks.push(BreakTarget::Loop);
            self.body(&f.body, indent + 1, out);
            self.breaks.pop();
            return;
        }
        match &f.init {
            None => {}
            Some(ForStatementInit::VariableDeclaration(v))
                if v.kind == VariableDeclarationKind::Let =>
            {
                self.var_decl(v, indent, out);
            }
            Some(other) => {
                self.refuse(
                    other.span(),
                    "C-style for loop init other than a let declaration",
                );
                return;
            }
        }
        let update = match &f.update {
            None => None,
            Some(Expression::AssignmentExpression(a)) => Some(a),
            Some(other) => {
                self.refuse(
                    other.span(),
                    "C-style for loop update other than an assignment",
                );
                return;
            }
        };
        if continues_out(&f.body) {
            self.refuse(f.span, "continue in a C-style for loop");
            return;
        }
        let test = match &f.test {
            Some(test) => self.condition(test),
            None => "True".to_string(),
        };
        out.push(format!("{p}while {test}:"));
        self.breaks.push(BreakTarget::Loop);
        self.body(&f.body, indent + 1, out);
        self.breaks.pop();
        if let Some(a) = update {
            self.assignment(a, indent + 1, out);
        }
    }

    /// J87-3: `try { ... } catch (e?) { ... }`. Python's `except` sees every exception; only what a
    /// JS `catch` could see is caught (`_js_catch`: a JS Error, an adapter's OSError, the runtime's
    /// JS-worded TypeError), anything else (a subset refusal) propagates. The handler runs after
    /// the `try` statement, outside the `except`, so nothing it raises is chained to what was
    /// caught: a JS throw carries no implicit cause. `finally` is refused.
    fn try_stmt(&mut self, t: &TryStatement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        if let Some(finalizer) = &t.finalizer {
            self.refuse(finalizer.span, "finally");
            return;
        }
        let Some(handler) = &t.handler else {
            self.refuse(t.span, "try without catch");
            return;
        };
        let n = self.tmp;
        self.tmp += 1;
        let caught = format!("_js_caught{n}");
        let error = format!("_js_error{n}");
        out.push(format!("{p}{caught} = None"));
        out.push(format!("{p}try:"));
        let start = out.len();
        self.block(&t.block.body, indent + 1, out);
        if out.len() == start {
            out.push(format!("{p}    pass"));
        }
        out.push(format!("{p}except Exception as {error}:"));
        out.push(format!("{p}    {caught} = _js_catch({error})"));
        out.push(format!("{p}if {caught} is not None:"));
        let mut bound = false;
        if let Some(param) = &handler.param {
            match &param.pattern {
                BindingPattern::BindingIdentifier(id) => {
                    if self.is_local(id.name.as_str()) {
                        self.refuse(id.span, "catch binding that shadows a binding");
                    } else {
                        self.catch_params
                            .push((id.name.to_string(), caught.clone()));
                        bound = true;
                    }
                }
                other => {
                    self.refuse(other.span(), "destructuring catch binding");
                }
            }
        }
        let start = out.len();
        self.block(&handler.body.body, indent + 1, out);
        if out.len() == start {
            out.push(format!("{p}    pass"));
        }
        if bound {
            self.catch_params.pop();
        }
    }

    /// `const` / `let` declarations (a statement, or the init of a C-style `for`, J87-3).
    fn var_decl(&mut self, v: &VariableDeclaration<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        if v.kind == VariableDeclarationKind::Var {
            self.refuse(v.span, "var declaration");
        } else if !matches!(
            v.kind,
            VariableDeclarationKind::Let | VariableDeclarationKind::Const
        ) {
            self.refuse(v.span, "using declaration");
        }
        for d in &v.declarations {
            let id = match &d.id {
                BindingPattern::BindingIdentifier(id) => id,
                BindingPattern::ArrayPattern(a) => {
                    self.array_pattern_decl(a, d.init.as_ref(), d.span, indent, out);
                    continue;
                }
                BindingPattern::ObjectPattern(o) => {
                    self.object_pattern_decl(o, d.init.as_ref(), d.span, indent, out);
                    continue;
                }
                _ => {
                    self.refuse(d.span, "destructuring declaration");
                    continue;
                }
            };
            let name = py_name(id.name.as_str(), false, false);
            self.declare_annotation(id.name.as_str(), d.type_annotation.as_deref());
            if v.kind == VariableDeclarationKind::Const
                && let Some(key) = self.var_key(id.name.as_str())
            {
                self.consts.insert(key);
            }
            // J86: `const f = (...) => ...` inside a function is a nested `def` (a closure).
            if let (Some(Expression::ArrowFunctionExpression(a)), VariableDeclarationKind::Const) =
                (&d.init, v.kind)
            {
                self.bind(id.name.as_str(), Fact::default());
                self.nested_def(&name, a, indent, out);
                continue;
            }
            let (value, fact) = match &d.init {
                Some(init) => {
                    let value = self.expr(init);
                    let fact = value.fact();
                    (value.code, fact)
                }
                None => ("_JS_UNDEFINED".to_string(), Fact::default()),
            };
            // J87: a `const` none of whose reads can let its value escape keeps the
            // contents of a fresh array it was bound to (`peek`).
            let held = v.kind == VariableDeclarationKind::Const
                && self
                    .var_key(id.name.as_str())
                    .is_some_and(|key| !self.assume.escaped_locals.contains(&key));
            if held && let Some(key) = self.var_key(id.name.as_str()) {
                self.observed.declared.insert(key.clone());
                self.observed.observe(key, fact);
            } else {
                self.bind_decl(id.name.as_str(), fact);
            }
            out.push(format!("{p}{name} = {value}"));
            self.hoist_line(id.name.as_str(), indent, out);
        }
    }

    fn assignment(&mut self, a: &AssignmentExpression<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        // J86: `a = b = v` (identifiers only): one value, every target bound to it.
        if a.operator == AssignmentOperator::Assign
            && let Expression::AssignmentExpression(_) = &a.right
        {
            let mut targets = Vec::new();
            let mut current = a;
            loop {
                let AssignmentTarget::AssignmentTargetIdentifier(id) = &current.left else {
                    self.refuse(current.span, "chained assignment to anything but a local");
                    return;
                };
                targets.push(id);
                match &current.right {
                    Expression::AssignmentExpression(next)
                        if next.operator == AssignmentOperator::Assign =>
                    {
                        current = next;
                    }
                    Expression::AssignmentExpression(next) => {
                        self.refuse(next.span, "compound assignment inside an expression");
                        return;
                    }
                    _ => break,
                }
            }
            let value = self.expr(&current.right);
            let mut names = Vec::new();
            for id in targets {
                names.push(self.local_target(id.name.as_str(), id.span).code);
                self.bind(id.name.as_str(), value.fact());
            }
            out.push(format!("{p}{} = {}", names.join(" = "), value.code));
            return;
        }
        let op = match a.operator {
            AssignmentOperator::Assign => None,
            AssignmentOperator::Addition => Some(BinaryOperator::Addition),
            AssignmentOperator::Subtraction => Some(BinaryOperator::Subtraction),
            AssignmentOperator::Multiplication => Some(BinaryOperator::Multiplication),
            _ => {
                self.refuse(a.span, "compound assignment operator");
                return;
            }
        };
        match &a.left {
            AssignmentTarget::AssignmentTargetIdentifier(id) => {
                let target = self.local_target(id.name.as_str(), id.span);
                let value = self.assigned_value(op, target.clone(), &a.right);
                self.bind(id.name.as_str(), value.fact());
                out.push(format!("{p}{} = {}", target.code, value.code));
            }
            AssignmentTarget::StaticMemberExpression(m)
                if matches!(strip(&m.object), Expression::ThisExpression(_)) =>
            {
                let target = self.this_member(m.property.name.as_str(), m.span);
                let value = self.assigned_value(op, target.clone(), &a.right);
                out.push(format!("{p}{} = {}", target.code, value.code));
            }
            AssignmentTarget::StaticMemberExpression(m) => {
                if op.is_some() {
                    self.refuse(a.span, "compound assignment to a property");
                    return;
                }
                let object = self.expr(&m.object);
                let value = self.expr(&a.right);
                out.push(format!(
                    "{p}_js_put({}, {}, {})",
                    object.code,
                    py_str(m.property.name.as_str()),
                    value.code
                ));
            }
            AssignmentTarget::ComputedMemberExpression(m) => {
                if op.is_some() {
                    self.refuse(a.span, "compound assignment to a property");
                    return;
                }
                let object = self.expr(&m.object);
                let key = self.expr(&m.expression);
                let value = self.expr(&a.right);
                out.push(format!(
                    "{p}_js_put({}, {}, {})",
                    object.code, key.code, value.code
                ));
            }
            AssignmentTarget::ArrayAssignmentTarget(t) if op.is_none() => {
                self.array_assignment(t, &a.right, indent, out);
            }
            other => {
                self.refuse(other.span(), "assignment target");
            }
        }
    }

    fn for_of(&mut self, f: &ForOfStatement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        if f.r#await {
            self.refuse(f.span, "for await");
            return;
        }
        let ForStatementLeft::VariableDeclaration(v) = &f.left else {
            self.refuse(f.left.span(), "for-of over an existing binding");
            return;
        };
        if v.kind == VariableDeclarationKind::Var || v.declarations.len() != 1 {
            self.refuse(v.span, "for-of declaration");
            return;
        }
        // J87: a frozen module array is read here without escaping: each element is destructured
        // at once, so nothing can hold (and mutate) it.
        let frozen = match (strip_parens(&f.right), &v.declarations[0].id) {
            (Expression::Identifier(id), BindingPattern::ArrayPattern(_))
                if self.frozen.contains(id.name.as_str()) && !self.is_scoped(id.name.as_str()) =>
            {
                Some(id)
            }
            _ => None,
        };
        let right = match frozen {
            Some(id) => self.global_read(id.name.as_str(), id.span, false),
            None => self.expr(&f.right),
        };
        // J87: what each element is: a string iterates by code point (each a `str`).
        let element = if right.top {
            Fact::top()
        } else if right.is_str {
            Fact::str_()
        } else {
            right.elem.as_deref().cloned().unwrap_or_default()
        };
        match &v.declarations[0].id {
            BindingPattern::BindingIdentifier(id) => {
                let name = py_name(id.name.as_str(), false, false);
                self.bind(id.name.as_str(), element.clone());
                out.push(format!("{p}for {name} in {}:", right.code));
            }
            BindingPattern::ArrayPattern(a) => {
                let mut names = Vec::new();
                for element in &a.elements {
                    match element {
                        Some(BindingPattern::BindingIdentifier(id)) => {
                            names.push(py_name(id.name.as_str(), false, false))
                        }
                        _ => {
                            self.refuse(a.span, "destructuring pattern");
                            return;
                        }
                    }
                }
                if a.rest.is_some() {
                    self.refuse(a.span, "destructuring rest element");
                    return;
                }
                let exact = element
                    .tuple
                    .as_ref()
                    .filter(|tuple| tuple.len() == names.len());
                for (i, item) in a.elements.iter().enumerate() {
                    if let Some(BindingPattern::BindingIdentifier(id)) = item {
                        let fact = if element.top {
                            Fact::top()
                        } else {
                            exact
                                .and_then(|tuple| tuple.get(i).cloned())
                                .unwrap_or_default()
                        };
                        self.bind(id.name.as_str(), fact);
                    }
                }
                if names.len() == 2 && is_entries_call(&f.right) {
                    // `.entries()` yields `[index, item]` pairs, so a plain unpack is exact.
                    out.push(format!(
                        "{p}for {}, {} in {}:",
                        names[0], names[1], right.code
                    ));
                } else if exact.is_some() {
                    // J87: every element is a fresh array of exactly this many items.
                    out.push(format!("{p}for {} in {}:", names.join(", "), right.code));
                } else {
                    let item = format!("_js_item{}", self.tmp);
                    self.tmp += 1;
                    out.push(format!("{p}for {item} in {}:", right.code));
                    for (i, name) in names.iter().enumerate() {
                        out.push(format!("{}{name} = _js_get({item}, {i})", pad(indent + 1)));
                    }
                }
            }
            other => {
                self.refuse(other.span(), "destructuring pattern");
                return;
            }
        }
        self.breaks.push(BreakTarget::Loop);
        self.body(&f.body, indent + 1, out);
        self.breaks.pop();
    }

    /// An expression in a condition slot: a Python bool, through `_js_truthy` unless it already is.
    fn condition(&mut self, e: &Expression<'_>) -> String {
        let value = self.peek(e);
        truthy(value).code
    }

    // ---------------------------------------------------------------- expressions

    fn expr(&mut self, e: &Expression<'_>) -> Py {
        match e {
            Expression::BooleanLiteral(b) => Py {
                pure: true,
                ..Py::boolean(if b.value { "True" } else { "False" }, ATOM)
            },
            Expression::NullLiteral(_) => Py {
                pure: true,
                is_null: true,
                ..Py::atom("None")
            },
            Expression::NumericLiteral(n) => match py_number(n.value) {
                Some(code) => {
                    let prec = if code.starts_with('-') { UNARY } else { ATOM };
                    Py {
                        is_num: true,
                        is_double: true,
                        pure: true,
                        ..Py::new(code, prec)
                    }
                }
                None => self.refuse(n.span, "non-finite number literal"),
            },
            Expression::StringLiteral(s) => {
                let units: Vec<u16> = s.value.encode_utf16().collect();
                Py {
                    is_str: true,
                    pure: true,
                    safe_start: !units.first().is_some_and(|u| is_trail(*u)),
                    safe_end: !units.last().is_some_and(|u| is_lead(*u)),
                    ..Py::atom(py_str_utf16(units))
                }
            }
            Expression::TemplateLiteral(t) => self.template(t),
            Expression::Identifier(id) => self.resolve(id.name.as_str(), id.span),
            Expression::ArrayExpression(a) => self.array(a),
            Expression::ObjectExpression(o) => self.object(o),
            Expression::BinaryExpression(b) => self.binary(b),
            Expression::LogicalExpression(l) => self.logical(l),
            Expression::UnaryExpression(u) => self.unary(u),
            Expression::ConditionalExpression(c) => {
                let test = self.expr(&c.test);
                let test = truthy(test);
                let yes = self.expr(&c.consequent);
                let no = self.expr(&c.alternate);
                let code = Py::new(
                    format!("{} if {} else {}", yes.at(OR), test.at(OR), no.at(TERNARY)),
                    TERNARY,
                );
                yes.meet_into(&no, code)
            }
            Expression::CallExpression(c) => self.call(c),
            Expression::NewExpression(n) => self.new_expr(n),
            Expression::StaticMemberExpression(m) => {
                if m.optional {
                    return self.refuse(m.span, "optional chaining");
                }
                // J87-3: `Number.MAX_SAFE_INTEGER`, the constant; `process.env.NAME`, the adapter.
                if let Expression::Identifier(id) = strip(&m.object)
                    && id.name == "Number"
                    && m.property.name == "MAX_SAFE_INTEGER"
                    && !self.is_local("Number")
                {
                    return Py {
                        is_num: true,
                        is_double: true,
                        pure: true,
                        ..Py::atom("9007199254740991")
                    };
                }
                if self.is_process_env(&m.object) {
                    let key = py_str(m.property.name.as_str());
                    return self.process_env_read(key);
                }
                // J86-R finding 3: this arm is never a call's callee (`call` takes that member
                // itself), so a callable name here is a method read as a value.
                // J87: unless the receiver's declared type makes the member a data field.
                if self.is_method_name(&m.object, m.property.name.as_str())
                    && !self.declared_data(&m.object, m.property.name.as_str())
                {
                    let construct = method_as_value(m.property.name.as_str());
                    return self.refuse(m.span, construct);
                }
                // J86: `this.x` is the attribute itself; `Object.prototype` a stand-in compared by
                // identity (`Object.getPrototypeOf(o) === Object.prototype`).
                if let Expression::ThisExpression(_) = strip(&m.object) {
                    return self.this_member(m.property.name.as_str(), m.span);
                }
                if let Expression::Identifier(id) = strip(&m.object)
                    && id.name == "Object"
                    && m.property.name == "prototype"
                    && !self.is_local("Object")
                {
                    return Py {
                        pure: true,
                        ..Py::atom("_JS_OBJECT_PROTOTYPE")
                    };
                }
                let object = self.member_object(&m.object);
                // J87: a read of an optimistic value is optimistic too (`types::Fact::top`).
                if object.top {
                    let read = match m.property.name.as_str() {
                        "length" => format!("_js_len({})", object.code),
                        "size" => format!("_js_size({})", object.code),
                        prop => format!("_js_get({}, {})", object.code, py_str(prop)),
                    };
                    return Py::atom(read).with_fact(None);
                }
                match m.property.name.as_str() {
                    // A known number only on a known string: on any other receiver `.length` is
                    // whatever the object holds (`{length: '1'}`), so it is compared, added and
                    // equated through the runtime, as any unknown value is (J85-R2 L1).
                    // J87: a proven `str` counts UTF-16 units without the dispatch; a proven list
                    // is its Python length.
                    "length" if object.is_str => match self.units_of(&m.object, true) {
                        Some(units) => returned(Ret::Num, format!("len({units})")),
                        None => returned(Ret::Num, format!("_js_str_len({})", object.code)),
                    },
                    "length" if object.is_list => {
                        returned(Ret::Num, format!("len({})", object.code))
                    }
                    "length" => Py::atom(format!("_js_len({})", object.code)),
                    "size" => Py::atom(format!("_js_size({})", object.code)),
                    prop => {
                        let read = Py::atom(format!("_js_get({}, {})", object.code, py_str(prop)));
                        self.frozen_member(&object, read)
                    }
                }
            }
            Expression::ComputedMemberExpression(m) => {
                if m.optional {
                    return self.refuse(m.span, "optional chaining");
                }
                // J87-3: `process.env[name]`, through the adapter.
                if self.is_process_env(&m.object) {
                    let key = self.expr(&m.expression);
                    return self.process_env_read(key.code);
                }
                // A literal key is a name (`xs['map']`); a computed one is checked at run time
                // (`_js_get` raises on a method name the receiver's JS type carries).
                if let Expression::StringLiteral(key) = strip(&m.expression)
                    && let Some(name) = key.value.as_str()
                    && self.is_method_name(&m.object, name)
                    && !self.declared_data(&m.object, name)
                {
                    let construct = method_as_value(name);
                    return self.refuse(m.span, construct);
                }
                let literal_index = match strip(&m.expression) {
                    Expression::NumericLiteral(n) if n.value >= 0.0 && n.value.fract() == 0.0 => {
                        Some(n.value as usize)
                    }
                    _ => None,
                };
                let object = if literal_index.is_some() {
                    match strip_parens(&m.object) {
                        Expression::Identifier(id) if self.is_scoped(id.name.as_str()) => {
                            self.peek(&m.object)
                        }
                        _ => self.member_object(&m.object),
                    }
                } else {
                    self.member_object(&m.object)
                };
                let key = self.expr(&m.expression);
                if object.top || key.top {
                    return Py::atom(format!("_js_get({}, {})", object.code, key.code))
                        .with_fact(None);
                }
                // J87: an index into a proven `str` is a `str` or `undefined`.
                let unit = |code: Py| Py {
                    nn: Some(Box::new(Fact::str_())),
                    no_null: true,
                    ..code
                };
                // J87: a hoisted view is indexed inline (a simple key) or by `_js_units_at`.
                if let Some(units) = self.units_of(&m.object, object.is_str) {
                    if let Some(k) = literal_index {
                        return unit(Py::new(
                            format!("{units}[{k}] if len({units}) > {k} else _JS_UNDEFINED"),
                            TERNARY,
                        ));
                    }
                    if key.pure && key.prec == ATOM {
                        let k = &key.code;
                        return unit(Py::new(
                            format!(
                                "{units}[{k}] if type({k}) is int and 0 <= {k} < len({units}) else _js_str_at({}, {k})",
                                object.code
                            ),
                            TERNARY,
                        ));
                    }
                    return unit(Py::atom(format!(
                        "_js_units_at({units}, {}, {})",
                        object.code, key.code
                    )));
                }
                // J87: an index into a proven `str` or list skips the receiver dispatch.
                if object.is_str {
                    return unit(Py::atom(format!(
                        "_js_str_at({}, {})",
                        object.code, key.code
                    )));
                }
                // J87: a literal index into a fresh (or held) array of known length is that element.
                if object.is_list
                    && let (Some(k), Some(tuple)) = (literal_index, &object.tuple)
                    && let Some(element) = tuple.get(k)
                {
                    // Shallow: the element's own array may be mutated through this one.
                    let element = element.shallow();
                    return Py::atom(format!("{}[{k}]", object.at(ATOM))).with_fact(Some(&element));
                }
                if object.is_list {
                    return Py::atom(format!("_js_list_at({}, {})", object.code, key.code));
                }
                let read = Py::atom(format!("_js_get({}, {})", object.code, key.code));
                // J87: element 0 of what `exec` returned is the matched `str` (reading it from
                // `null` is the TypeError JS raises too).
                if object.is_match
                    && matches!(strip(&m.expression), Expression::NumericLiteral(n) if n.value == 0.0)
                {
                    return Py {
                        is_str: true,
                        ..read
                    };
                }
                self.frozen_member(&object, read)
            }
            Expression::RegExpLiteral(r) => self.regex(r),
            Expression::ParenthesizedExpression(p) => self.expr(&p.expression),
            Expression::TSAsExpression(x) => self.expr(&x.expression),
            Expression::TSSatisfiesExpression(x) => self.expr(&x.expression),
            Expression::TSNonNullExpression(x) => self.expr(&x.expression),
            Expression::TSTypeAssertion(x) => self.expr(&x.expression),
            Expression::TSInstantiationExpression(x) => self.expr(&x.expression),
            Expression::ArrowFunctionExpression(a) => {
                self.refuse(a.span, "arrow function outside a callback argument")
            }
            Expression::ThisExpression(t) => {
                if self.class_ctx.is_some() {
                    Py {
                        pure: true,
                        ..Py::atom("self")
                    }
                } else {
                    self.refuse(t.span, "this outside a class")
                }
            }
            Expression::AwaitExpression(a) => self.refuse(a.span, "await"),
            Expression::YieldExpression(y) => self.refuse(y.span, "yield"),
            Expression::ClassExpression(c) => self.refuse(c.span, "class"),
            Expression::FunctionExpression(f) => self.refuse(f.span, "function expression"),
            Expression::AssignmentExpression(a) => {
                self.refuse(a.span, "assignment inside an expression")
            }
            Expression::UpdateExpression(u) => self.refuse(u.span, "update expression (++/--)"),
            Expression::ChainExpression(c) => self.chain(c),
            Expression::SequenceExpression(s) => self.refuse(s.span, "comma operator"),
            Expression::TaggedTemplateExpression(t) => self.refuse(t.span, "tagged template"),
            // J86: a BigInt is `_JsBigInt` (exact, never equal to a number).
            Expression::BigIntLiteral(b) => Py {
                pure: true,
                ..Py::atom(format!("_JsBigInt({})", b.value.as_str()))
            },
            other => self.refuse(other.span(), "expression"),
        }
    }

    /// J87-3: `o?.k` / `o?.[k]`, one optional member read whose object holds no other optional link
    /// (`_js_opt_get`: `undefined` when `o` is null or undefined, else the read). An optional call,
    /// a link after the optional one (`o?.k.j`) and a chain of them stay refused.
    fn chain(&mut self, c: &ChainExpression<'_>) -> Py {
        fn has_optional(e: &Expression<'_>) -> bool {
            match strip(e) {
                Expression::StaticMemberExpression(m) => m.optional || has_optional(&m.object),
                Expression::ComputedMemberExpression(m) => m.optional || has_optional(&m.object),
                Expression::CallExpression(call) => call.optional || has_optional(&call.callee),
                _ => false,
            }
        }
        let (object, key, optional, span) = match &c.expression {
            ChainElement::StaticMemberExpression(m) => {
                let name = m.property.name.as_str();
                if self.is_method_name(&m.object, name) && !self.declared_data(&m.object, name) {
                    let construct = method_as_value(name);
                    return self.refuse(m.span, construct);
                }
                (&m.object, None, m.optional, m.span)
            }
            ChainElement::ComputedMemberExpression(m) => {
                if let Expression::StringLiteral(key) = strip(&m.expression)
                    && let Some(name) = key.value.as_str()
                    && self.is_method_name(&m.object, name)
                    && !self.declared_data(&m.object, name)
                {
                    let construct = method_as_value(name);
                    return self.refuse(m.span, construct);
                }
                (&m.object, Some(&m.expression), m.optional, m.span)
            }
            _ => return self.refuse(c.span, "optional chaining other than one member read"),
        };
        if !optional || has_optional(object) {
            return self.refuse(span, "optional chaining other than one member read");
        }
        let object = self.member_object(object);
        let key = match (key, &c.expression) {
            (Some(e), _) => self.expr(e).code,
            (None, ChainElement::StaticMemberExpression(m)) => py_str(m.property.name.as_str()),
            (None, _) => unreachable!("a static member read"),
        };
        Py::atom(format!("_js_opt_get({}, {key})", object.code))
    }

    /// J87-3: `e` is `process.env`, with `process` the Node global (not a binding).
    fn is_process_env(&self, e: &Expression<'_>) -> bool {
        matches!(strip(e), Expression::StaticMemberExpression(env)
            if env.property.name == "env"
                && !env.optional
                && matches!(strip(&env.object), Expression::Identifier(p)
                    if p.name == "process" && !self.is_local("process")))
    }

    /// J87-3: a read of the process environment (`adapters.rs`, `process.env`): a string, or
    /// `undefined` when the variable is unset.
    fn process_env_read(&mut self, key: String) -> Py {
        let adapter = adapters::global("process.env").expect("declared in adapters.rs");
        self.imports
            .entry(self.ctx.adapter_module.clone())
            .or_default()
            .insert(adapter.py_name.to_string());
        Py {
            no_null: true,
            ..Py::atom(format!("{}({key})", adapter.py_name))
        }
    }

    /// J87-3: `a ** b` of two non-negative integer literals whose power is an integer a double
    /// holds exactly (at most 2^53), folded to that integer: the one exponentiation whose JS
    /// value is beyond doubt. Every other `**` is refused (V8's `**` and CPython's `pow` part in
    /// the last bit for some operands, and a negative base or a fraction has JS-only rules).
    fn exponent(&mut self, b: &BinaryExpression<'_>) -> Py {
        let literal = |e: &Expression<'_>| match strip(e) {
            Expression::NumericLiteral(n)
                if n.value >= 0.0 && n.value.fract() == 0.0 && n.value <= 1e15 =>
            {
                Some(n.value as u128)
            }
            _ => None,
        };
        if let (Some(base), Some(power)) = (literal(&b.left), literal(&b.right))
            && let Ok(power) = u32::try_from(power)
            && let Some(value) = base.checked_pow(power)
            && value <= 1u128 << 53
        {
            return Py {
                is_num: true,
                is_double: true,
                pure: true,
                ..Py::atom(value.to_string())
            };
        }
        self.refuse(
            b.span,
            "operator ** other than of two integer literals with an exact result",
        )
    }

    fn template(&mut self, t: &TemplateLiteral<'_>) -> Py {
        // Each part: its code, and whether its ends are known safe (SUBSET.md, Strings: a junction
        // where a lead surrogate may meet a trail surrogate is joined by `_js_cat`, J86).
        let mut parts: Vec<(String, bool, bool)> = Vec::new();
        for (i, quasi) in t.quasis.iter().enumerate() {
            match quasi.value.cooked {
                Some(cooked) => {
                    let units: Vec<u16> = cooked.encode_utf16().collect();
                    if !units.is_empty() {
                        parts.push((
                            py_str_utf16(units.iter().copied()),
                            !is_trail(units[0]),
                            !is_lead(units[units.len() - 1]),
                        ));
                    }
                }
                None => {
                    return self.refuse(quasi.span, "template escape");
                }
            }
            if let Some(e) = t.expressions.get(i) {
                let value = self.expr(e);
                let code = if value.is_str {
                    value.at(ADD + 1)
                } else {
                    format!("_js_str({})", value.code)
                };
                parts.push((code, value.safe_start, value.safe_end));
            }
        }
        if parts.is_empty() {
            return Py {
                is_str: true,
                pure: true,
                safe_start: true,
                safe_end: true,
                ..Py::atom("\"\"")
            };
        }
        let safe_start = parts[0].1;
        let mut parts = parts.into_iter();
        let (first, _, mut end_safe) = parts.next().expect("not empty");
        let mut code = first;
        let mut prec = ATOM;
        for (part, start_safe, part_end_safe) in parts {
            if end_safe || start_safe {
                code = format!("{code} + {part}");
                prec = ADD;
            } else {
                code = format!("_js_cat({code}, {part})");
                prec = ATOM;
            }
            end_safe = part_end_safe;
        }
        Py {
            is_str: true,
            safe_start,
            safe_end: end_safe,
            ..Py::new(code, prec)
        }
    }

    fn array(&mut self, a: &ArrayExpression<'_>) -> Py {
        let mut items = Vec::new();
        let mut facts = Vec::new();
        let mut spread = false;
        for element in &a.elements {
            match element {
                ArrayExpressionElement::SpreadElement(s) => {
                    let value = self.expr(&s.argument);
                    items.push(format!("*{}", value.at(ATOM)));
                    spread = true;
                }
                ArrayExpressionElement::Elision(e) => {
                    self.refuse(e.span, "array hole");
                }
                other => {
                    let e = other
                        .as_expression()
                        .expect("an array element is an expression");
                    let value = self.expr(e);
                    facts.push(value.fact());
                    items.push(value.code);
                }
            }
        }
        // J87: a fresh list; without a spread, its exact length and each element's facts.
        let tuple = if spread { None } else { Some(facts) };
        let elem = tuple.as_ref().and_then(|facts| {
            let mut all = facts.iter();
            let first = all.next()?.clone();
            Some(Box::new(all.fold(first, |acc, f| acc.meet(f))))
        });
        Py {
            pure: items.is_empty(),
            is_list: true,
            tuple,
            elem,
            ..Py::atom(format!("[{}]", items.join(", ")))
        }
    }

    fn object(&mut self, o: &ObjectExpression<'_>) -> Py {
        let mut items = Vec::new();
        // J87: what every property value is (kept only by a frozen module object).
        let mut values: Option<Fact> = None;
        let mut spread = false;
        for property in &o.properties {
            match property {
                // J86: `{...x}` copies x's own enumerable properties (`_js_spread`), in place.
                ObjectPropertyKind::SpreadProperty(s) => {
                    let value = self.expr(&s.argument);
                    items.push(format!("**_js_spread({})", value.code));
                    spread = true;
                }
                ObjectPropertyKind::ObjectProperty(p) => {
                    if p.method || p.kind != PropertyKind::Init {
                        self.refuse(p.span, "object method or accessor");
                        continue;
                    }
                    if p.computed {
                        self.refuse(p.span, "computed property key");
                        continue;
                    }
                    let key = match &p.key {
                        PropertyKey::StaticIdentifier(id) => id.name.to_string(),
                        PropertyKey::StringLiteral(s) => match s.value.as_str() {
                            Some(text) => text.to_string(),
                            None => {
                                self.refuse(s.span, "property key with a lone surrogate");
                                continue;
                            }
                        },
                        other => {
                            self.refuse(other.span(), "property key");
                            continue;
                        }
                    };
                    if is_array_index(&key) {
                        self.refuse(p.span, "integer-like property key");
                        continue;
                    }
                    let value = self.expr(&p.value);
                    let fact = value.fact();
                    values = Some(match values {
                        Some(all) => all.meet(&fact),
                        None => fact,
                    });
                    items.push(format!("{}: {}", py_str(&key), value.code));
                }
            }
        }
        Py {
            pure: items.is_empty(),
            elem: values.filter(|_| !spread).map(Box::new),
            ..Py::atom(format!("{{{}}}", items.join(", ")))
        }
    }

    fn binary(&mut self, b: &BinaryExpression<'_>) -> Py {
        use BinaryOperator as Op;
        match b.operator {
            Op::StrictEquality | Op::StrictInequality => {
                let negate = b.operator == Op::StrictInequality;
                self.strict_eq(&b.left, &b.right, negate)
            }
            Op::Equality | Op::Inequality => {
                let negate = b.operator == Op::Inequality;
                let other = if is_nullish_literal(&b.right) {
                    &b.left
                } else if is_nullish_literal(&b.left) {
                    &b.right
                } else {
                    return self.refuse(b.span, "loose equality other than == null");
                };
                let value = self.peek(other);
                let test = format!("_js_is_nullish({})", value.code);
                if negate {
                    Py::boolean(format!("not {test}"), NOT)
                } else {
                    Py::boolean(test, ATOM)
                }
            }
            Op::LessThan | Op::LessEqualThan | Op::GreaterThan | Op::GreaterEqualThan => {
                let (left, right) = (self.expr(&b.left), self.expr(&b.right));
                if !(left.is_num && right.is_num) {
                    // Not two known numbers: JS's Abstract Relational Comparison, in the runtime.
                    // Two strings compare by UTF-16 code unit (Python's `<` is by code point),
                    // and anything else goes through ToPrimitive and ToNumber (SUBSET.md).
                    let helper = match b.operator {
                        Op::LessThan => "_js_lt",
                        Op::LessEqualThan => "_js_le",
                        Op::GreaterThan => "_js_gt",
                        _ => "_js_ge",
                    };
                    return Py::boolean(format!("{helper}({}, {})", left.code, right.code), ATOM);
                }
                let left = js_num(left);
                let right = js_num(right);
                Py::boolean(
                    format!(
                        "{} {} {}",
                        left.at(CMP + 1),
                        b.operator.as_str(),
                        right.at(CMP + 1)
                    ),
                    CMP,
                )
            }
            Op::Subtraction | Op::Addition | Op::Multiplication | Op::Division | Op::Remainder => {
                let left = self.expr(&b.left);
                let right = self.expr(&b.right);
                arith(b.operator, left, right)
            }

            Op::Exponential => self.exponent(b),
            // J86: `key in obj`, own keys plus what Object.prototype supplies.
            Op::In => {
                let key = self.expr(&b.left);
                let object = self.expr(&b.right);
                Py::boolean(format!("_js_in({}, {})", key.code, object.code), ATOM)
            }
            // J86: `x instanceof C` for a compiled class or a built-in Error class.
            Op::Instanceof => {
                let value = self.expr(&b.left);
                match self.class_ref(&b.right) {
                    Some(class) => {
                        Py::boolean(format!("isinstance({}, {class})", value.code), ATOM)
                    }
                    None => {
                        self.refuse(b.span, "instanceof anything but a compiled or Error class")
                    }
                }
            }
            other => {
                let construct = format!("operator {}", other.as_str());
                self.refuse(b.span, construct)
            }
        }
    }

    fn strict_eq(&mut self, left: &Expression<'_>, right: &Expression<'_>, negate: bool) -> Py {
        // J87: comparing a local with null or undefined does not let its value escape.
        let l = if is_nullish_literal(right) {
            self.peek(left)
        } else {
            self.expr(left)
        };
        let r = if is_nullish_literal(left) {
            self.peek(right)
        } else {
            self.expr(right)
        };
        self.strict_eq_parts(l, Some(left), r, right, negate)
    }

    /// `subject === <test>` with the subject already lowered (a `switch` discriminant, J86).
    fn strict_eq_py(&mut self, l: Py, r: Py, right: &Expression<'_>, negate: bool) -> Py {
        self.strict_eq_parts(l, None, r, right, negate)
    }

    fn strict_eq_parts(
        &mut self,
        l: Py,
        left: Option<&Expression<'_>>,
        r: Py,
        right: &Expression<'_>,
        negate: bool,
    ) -> Py {
        // `x === null` / `x === undefined`: identity against the one sentinel.
        for (value, other) in [(&l, Some(right)), (&r, left)] {
            let Some(other) = other else { continue };
            let literal = match strip(other) {
                Expression::NullLiteral(_) => Some("None"),
                Expression::Identifier(id)
                    if id.name == "undefined" && !self.is_local("undefined") =>
                {
                    Some("_JS_UNDEFINED")
                }
                _ => None,
            };
            if let Some(literal) = literal {
                let op = if negate { "is not" } else { "is" };
                return Py::boolean(format!("{} {op} {literal}", value.at(CMP + 1)), CMP);
            }
        }
        // Against a string literal, Python `==` is already exact: it never equates a str with
        // anything that is not a str. Two known numbers compare by value in both languages.
        // J87: two proven bools compare by value in both languages too.
        let exact = l.is_str || r.is_str || (l.is_num && r.is_num) || (l.is_bool && r.is_bool);
        if exact {
            let (l, r) = if l.is_str || r.is_str {
                (l, r)
            } else {
                (js_num(l), js_num(r))
            };
            let op = if negate { "!=" } else { "==" };
            return Py::boolean(format!("{} {op} {}", l.at(CMP + 1), r.at(CMP + 1)), CMP);
        }
        let test = format!("_js_strict_eq({}, {})", l.code, r.code);
        if negate {
            Py::boolean(format!("not {test}"), NOT)
        } else {
            Py::boolean(test, ATOM)
        }
    }

    fn logical(&mut self, l: &LogicalExpression<'_>) -> Py {
        let left = self.expr(&l.left);
        let right = self.expr(&l.right);
        match l.operator {
            LogicalOperator::And | LogicalOperator::Or if left.is_bool && right.is_bool => {
                let (op, prec) = if l.operator == LogicalOperator::And {
                    ("and", AND)
                } else {
                    ("or", OR)
                };
                Py::boolean(
                    format!("{} {op} {}", left.at(prec), right.at(prec + 1)),
                    prec,
                )
            }
            op => {
                let helper = match op {
                    LogicalOperator::And => "_js_and",
                    LogicalOperator::Or => "_js_or",
                    LogicalOperator::Coalesce => "_js_coalesce",
                };
                let code = if right.pure {
                    format!("{helper}_value({}, {})", left.code, right.code)
                } else {
                    format!("{helper}({}, lambda: {})", left.code, right.code)
                };
                // The value is one of the two operands (J87: so is what it proves).
                let both = left.meet_into(&right, Py::atom(code));
                Py {
                    is_bool: false,
                    ..both
                }
            }
        }
    }

    fn unary(&mut self, u: &UnaryExpression<'_>) -> Py {
        match u.operator {
            UnaryOperator::LogicalNot => {
                let value = truthy(self.peek(&u.argument));
                Py::boolean(format!("not {}", value.at(NOT)), NOT)
            }
            UnaryOperator::UnaryNegation => {
                // J86: only a non-zero literal is negated in place; anything else may be 0 (whose
                // negation is -0, which only a float holds) or a BigInt, so `_js_neg`.
                if !matches!(strip(&u.argument), Expression::NumericLiteral(n) if n.value != 0.0) {
                    let value = self.expr(&u.argument);
                    let optimistic = value.top;
                    let negated = Py {
                        is_num: value.is_num,
                        is_double: true,
                        pure: value.pure,
                        ..Py::atom(format!("_js_neg({})", value.code))
                    };
                    return if optimistic {
                        negated.with_fact(None)
                    } else {
                        negated
                    };
                }
                // Negating a double is exact, so normalising the operand is enough.
                let value = js_num(self.expr(&u.argument));
                Py {
                    is_num: true,
                    is_double: true,
                    pure: value.pure,
                    ..Py::new(format!("-{}", value.at(UNARY)), UNARY)
                }
            }
            UnaryOperator::Typeof => {
                let value = self.expr(&u.argument);
                Py {
                    is_str: true,
                    ..Py::atom(format!("_js_typeof({})", value.code))
                }
            }
            other => {
                let construct = format!("operator {}", other.as_str());
                self.refuse(u.span, construct)
            }
        }
    }

    fn args(
        &mut self,
        args: &[Argument<'_>],
        callback: Option<usize>,
        spread_ok: bool,
    ) -> Option<Vec<String>> {
        let lowered = self.args_py(args, callback, spread_ok)?;
        Some(lowered.into_iter().map(|a| a.code).collect())
    }

    /// The arguments lowered, with what each proves (J87). A spread argument's code starts `*`.
    fn args_py(
        &mut self,
        args: &[Argument<'_>],
        callback: Option<usize>,
        spread_ok: bool,
    ) -> Option<Vec<Py>> {
        let mut out = Vec::new();
        for (i, arg) in args.iter().enumerate() {
            let Some(e) = arg.as_expression() else {
                if let Argument::SpreadElement(spread) = arg
                    && spread_ok
                {
                    // J86: `a.push(...xs)` spreads any iterable, as a Python `*xs` does.
                    let value = self.expr(&spread.argument);
                    out.push(Py::atom(format!("*{}", value.at(ATOM))));
                    continue;
                }
                self.refuse(arg.span(), "spread argument");
                return None;
            };
            if callback == Some(i) {
                match strip(e) {
                    Expression::ArrowFunctionExpression(a) => out.push(self.callback(a)),
                    other => {
                        self.refuse(
                            other.span(),
                            "callback that is not an inline arrow function",
                        );
                        return None;
                    }
                }
            } else {
                out.push(self.expr(e));
            }
        }
        Some(out)
    }

    /// An inline arrow passed as a callback: a lambda that also swallows the index and array JS
    /// passes after the element. A parameter may be an array pattern of names (J86), read through
    /// the iterator as a declaration's pattern is.
    fn callback(&mut self, a: &ArrowFunctionExpression<'_>) -> Py {
        if a.r#async {
            return self.refuse(a.span, "async function");
        }
        let body = match &a.body {
            ArrowFunctionBody::FunctionBody(b) => {
                return self.refuse(b.span, "block-bodied arrow function in a callback");
            }
            other => other
                .as_expression()
                .expect("an arrow body is a block or an expression"),
        };
        if a.params.rest.is_some() {
            return self.refuse(a.span, "rest parameter");
        }
        let mut params: Vec<String> = Vec::new();
        let mut scope: HashSet<String> = HashSet::new();
        // (argument name, the names it destructures into)
        let mut unpack: Vec<(String, Vec<String>)> = Vec::new();
        for p in &a.params.items {
            if p.initializer.is_some() {
                return self.refuse(p.span, "default parameter in a callback");
            }
            match &p.pattern {
                BindingPattern::BindingIdentifier(id) => {
                    let py = py_name(id.name.as_str(), false, false);
                    self.claim(id.name.as_str(), &py, id.span);
                    scope.insert(id.name.to_string());
                    params.push(py);
                }
                BindingPattern::ArrayPattern(pattern) if pattern.rest.is_none() => {
                    let mut names = Vec::new();
                    for element in &pattern.elements {
                        match element {
                            Some(BindingPattern::BindingIdentifier(id)) => {
                                let py = py_name(id.name.as_str(), false, false);
                                self.claim(id.name.as_str(), &py, id.span);
                                scope.insert(id.name.to_string());
                                names.push(py);
                            }
                            None => names.push("_".to_string()),
                            Some(other) => {
                                return self.refuse(other.span(), "destructuring pattern");
                            }
                        }
                    }
                    let arg = format!("_js_arg{}", self.tmp);
                    self.tmp += 1;
                    params.push(arg.clone());
                    unpack.push((arg, names));
                }
                other => return self.refuse(other.span(), "destructuring parameter"),
            }
        }
        let callback_params: Vec<String> = scope.iter().cloned().collect();
        self.push_scope(scope, a.span.start);
        for name in callback_params {
            self.bind(&name, Fact::default());
        }
        self.rets.push(None);
        let value = self.expr(body);
        self.rets.pop();
        self.pop_scope();
        let mut code = value.at(TERNARY);
        for (arg, names) in unpack.iter().rev() {
            code = format!(
                "(lambda {}: {code})(*_js_destructure({arg}, {}))",
                names.join(", "),
                names.len()
            );
        }
        params.push("*_".to_string());
        Py::new(format!("lambda {}: {code}", params.join(", ")), LAMBDA)
    }

    /// J87: a direct call of a module function: its typed body when every guarded parameter's
    /// argument is proven, else its guarded entry (which the call makes it need). The result
    /// carries what the body (or both bodies) proved of its returns.
    fn module_call(&mut self, name: &str, sig: &Sig, c: &CallExpression<'_>) -> Py {
        let Some(args) = self.args_py(&c.arguments, None, false) else {
            return Py::atom("None");
        };
        let codes: Vec<String> = args.iter().map(|a| a.code.clone()).collect();
        let proven = sig.params.iter().enumerate().all(|(i, need)| match need {
            None => true,
            Some(need) => args.get(i).is_some_and(|a| a.fact().covers(need)),
        });
        let ret = |typed: bool| Key::Ret {
            name: name.to_string(),
            typed,
        };
        let (callee, fact) = if !sig.typed() {
            (sig.py.clone(), self.lookup(&ret(false)))
        } else if proven {
            let callee = if self.is_wrapped(name) {
                sig.typed_py.clone()
            } else {
                sig.py.clone()
            };
            (callee, self.lookup(&ret(true)))
        } else {
            self.observed.wrapped.insert(name.to_string());
            let typed = self.lookup(&ret(true));
            let untyped = self.lookup(&ret(false));
            let fact = match (typed, untyped) {
                (Some(a), Some(b)) => Some(a.meet(&b)),
                (Some(only), None) | (None, Some(only)) => Some(only),
                (None, None) => None,
            };
            (sig.py.clone(), fact)
        };
        // J87-3: what the call proves is what every return of the body proved (the fixpoint's
        // return facts); the `: boolean` annotation the J85 rule trusted is not proof.
        Py::atom(format!("{callee}({})", codes.join(", "))).with_fact(fact.as_ref())
    }

    /// J87: a builtin method on a receiver PROVEN to be a list, a string or a regex, lowered to the
    /// helper (or Python operation) that answers as the general one does for that receiver. None
    /// when no fast path covers the call; the caller lowers it the general way.
    fn fast_method(
        &mut self,
        method: &str,
        receiver: &Py,
        args: &[Py],
        as_statement: bool,
        call: &CallExpression<'_>,
        object: &Expression<'_>,
    ) -> Option<Py> {
        let spread = args.iter().any(|a| a.code.starts_with('*'));
        if spread {
            return None;
        }
        let all = |extra: &[Py]| -> String {
            let mut codes = vec![receiver.code.clone()];
            codes.extend(extra.iter().map(|a| a.code.clone()));
            codes.join(", ")
        };
        let one_str = args.len() == 1 && args[0].is_str;
        match method {
            "push" if receiver.is_list && !args.is_empty() => {
                if as_statement && args.len() == 1 {
                    // The new length is discarded, so appending is the whole effect.
                    return Some(Py::atom(format!(
                        "{}.append({})",
                        receiver.at(ATOM),
                        args[0].code
                    )));
                }
                Some(returned(Ret::Num, format!("_js_m_push({})", all(args))))
            }
            "includes" if receiver.is_list && one_str && (receiver.pure || args[0].pure) => {
                // SameValueZero against a `str` holds for an equal `str` element and nothing else,
                // which is what `in` tests (no runtime value but a `str` compares equal to one).
                Some(Py::boolean(
                    format!("{} in {}", args[0].at(CMP + 1), receiver.at(CMP + 1)),
                    CMP,
                ))
            }
            "includes" if receiver.is_str && one_str => Some(returned(
                Ret::Bool,
                format!("_js_str_includes({})", all(args)),
            )),
            // J87: a hoisted UTF-16 view answers an ASCII literal needle without a lookup.
            // The helpers take any position (and any slice bound) the general way, so only the
            // receiver (and the needle) need the proof.
            "indexOf"
                if receiver.is_str
                    && !args.is_empty()
                    && args.len() <= 2
                    && matches!(call.arguments.first().and_then(|a| a.as_expression()).map(strip),
                        Some(Expression::StringLiteral(l)) if l.value.as_str().is_some_and(str::is_ascii))
                    && let Some(units) = self.units_of(object, true) =>
            {
                let mut codes = vec![units];
                codes.extend(args.iter().map(|a| a.code.clone()));
                Some(returned(
                    Ret::Num,
                    format!("_js_units_index_of({})", codes.join(", ")),
                ))
            }
            "slice"
                if receiver.is_str
                    && args.len() <= 2
                    && let Some(units) = self.units_of(object, true) =>
            {
                let mut codes = vec![units];
                codes.extend(args.iter().map(|a| a.code.clone()));
                Some(returned(
                    Ret::Str,
                    format!("_js_units_slice({})", codes.join(", ")),
                ))
            }
            "join" if receiver.is_list && args.len() <= 1 && args.iter().all(|a| a.is_str) => {
                let separator = args.first().map_or("\",\"".to_string(), |a| a.code.clone());
                Some(returned(
                    Ret::Str,
                    format!("_js_list_join({}, {separator})", receiver.code),
                ))
            }
            "exec" if receiver.is_regex && one_str => {
                Some(returned(Ret::Match, format!("_js_re_exec({})", all(args))))
            }
            "replace"
                if receiver.is_str
                    && args.len() == 2
                    && args[0].is_regex
                    && matches!(call.arguments.get(1).and_then(|a| a.as_expression()).map(strip),
                        Some(Expression::StringLiteral(l))
                            if l.value.as_str().is_some_and(|v| !v.contains(['$', '\\']))) =>
            {
                Some(returned(Ret::Str, format!("_js_re_replace({})", all(args))))
            }
            "startsWith" if receiver.is_str && one_str => Some(returned(
                Ret::Bool,
                format!("_js_str_starts_with({})", all(args)),
            )),
            "indexOf"
                if receiver.is_str && !args.is_empty() && args.len() <= 2 && args[0].is_str =>
            {
                Some(returned(
                    Ret::Num,
                    format!("_js_str_index_of({})", all(args)),
                ))
            }
            "slice" if receiver.is_str && args.len() <= 2 => {
                Some(returned(Ret::Str, format!("_js_str_slice({})", all(args))))
            }
            "test" if receiver.is_regex && one_str => Some(Py::boolean(
                format!(
                    "{}.search(_js_code_units({})) is not None",
                    receiver.at(ATOM),
                    args[0].code
                ),
                CMP,
            )),
            _ => None,
        }
    }

    fn call(&mut self, c: &CallExpression<'_>) -> Py {
        // J87: the call is a whole expression statement (its value is discarded).
        let as_statement = std::mem::take(&mut self.statement_call);
        if c.optional {
            return self.refuse(c.span, "optional call");
        }
        match strip(&c.callee) {
            Expression::Identifier(id) => {
                let name = id.name.as_str();
                if !self.is_local(name)
                    && let Some(&(_, helper, min, max, ret)) =
                        GLOBAL_CALLS.iter().find(|(n, ..)| *n == name)
                {
                    if c.arguments.len() < min || c.arguments.len() > max {
                        let construct = format!("argument count for {name}()");
                        return self.refuse(c.span, construct);
                    }
                    let Some(args) = self.args(&c.arguments, None, false) else {
                        return Py::atom("None");
                    };
                    return returned(ret, format!("{helper}({})", args.join(", ")));
                }
                if self.classes.contains_key(name) && !self.scopes.iter().any(|s| s.contains(name))
                {
                    return self.refuse(c.span, "calling a class without new");
                }
                if !self.is_scoped(name)
                    && let Some(sig) = self.sigs.get(name).cloned()
                {
                    return self.module_call(name, &sig, c);
                }
                let callee = self.resolve(name, id.span);
                let Some(args) = self.args(&c.arguments, None, false) else {
                    return Py::atom("None");
                };
                Py::atom(format!("{}({})", callee.code, args.join(", ")))
            }
            Expression::StaticMemberExpression(m) => {
                if m.optional {
                    return self.refuse(m.span, "optional chaining");
                }
                let method = m.property.name.as_str();
                // J86: `this.m(...)` calls a method the class declares, directly.
                if let Expression::ThisExpression(_) = strip(&m.object) {
                    let declared = self
                        .class_ctx
                        .as_ref()
                        .is_some_and(|class| class.methods.contains(method));
                    if !declared {
                        let construct =
                            format!("this.{method}() for a method the class does not declare");
                        return self.refuse(c.span, construct);
                    }
                    let Some(args) = self.args(&c.arguments, None, false) else {
                        return Py::atom("None");
                    };
                    return Py::atom(format!("self.{method}({})", args.join(", ")));
                }
                if let Expression::Identifier(object) = strip(&m.object)
                    && !self.is_local(object.name.as_str())
                {
                    return self.static_call(object.name.as_str(), method, c);
                }
                let builtin = METHODS.iter().find(|(name, ..)| *name == method);
                let class_method = self.ctx.class_methods.contains(method);
                let Some(&(_, min, max, callback, ret)) = builtin else {
                    if class_method {
                        // J86: a method a compiled class (or an adapter class) declares.
                        let receiver = self.expr(&m.object);
                        let Some(args) = self.args(&c.arguments, None, false) else {
                            return Py::atom("None");
                        };
                        let mut all = vec![receiver.code, py_str(method)];
                        all.extend(args);
                        return Py::atom(format!("_js_invoke({})", all.join(", ")));
                    }
                    let construct = format!("builtin method .{method}");
                    return self.refuse(c.span, construct);
                };
                // A name a class shares with a builtin is dispatched at run time, so the builtin's
                // arity is checked only when no class could be the receiver.
                if !class_method && (c.arguments.len() < min || c.arguments.len() > max) {
                    let construct = format!("argument count for .{method}");
                    return self.refuse(c.span, construct);
                }
                // J87-3: an adapter function may be `.sort`'s comparator (`xs.sort(cmpCodepoint)`):
                // `_js_m_sort` calls it with exactly the two values JS passes.
                let callback = match c.arguments.first().and_then(Argument::as_expression) {
                    Some(Expression::Identifier(id))
                        if method == "sort"
                            && self.adapter_fns.contains(id.name.as_str())
                            && !self.is_scoped(id.name.as_str()) =>
                    {
                        None
                    }
                    _ => callback,
                };
                let receiver = self.expr(&m.object);
                let Some(args) = self.args_py(&c.arguments, callback, method == "push") else {
                    return Py::atom("None");
                };
                let optimistic = receiver.top || args.iter().any(|a| a.top);
                if !optimistic
                    && (class_method || (args.len() >= min && args.len() <= max))
                    && let Some(fast) =
                        self.fast_method(method, &receiver, &args, as_statement, c, &m.object)
                {
                    return fast;
                }
                let args: Vec<String> = args.into_iter().map(|a| a.code).collect();
                if class_method && method != "toString" {
                    // J86: a compiled class also declares this name, so the receiver decides, as
                    // JS's prototype lookup does: the instance's method, else the builtin.
                    // (`_js_m_toString` dispatches to an instance itself.)
                    let mut all = vec![receiver.code, py_str(method), format!("_js_m_{method}")];
                    all.extend(args);
                    return Py::atom(format!("_js_dispatch({})", all.join(", ")));
                }
                let mut all = vec![receiver.code];
                all.extend(args);
                let result = returned(ret, format!("_js_m_{method}({})", all.join(", ")));
                if optimistic {
                    return result.with_fact(None);
                }
                result
            }
            other => self.refuse(other.span(), "call of a computed callee"),
        }
    }

    fn static_call(&mut self, object: &str, method: &str, c: &CallExpression<'_>) -> Py {
        let Some(&(_, _, helper, min, max, ret)) = STATIC_CALLS
            .iter()
            .find(|(o, m, ..)| *o == object && *m == method)
        else {
            let construct = format!("builtin call {object}.{method}");
            return self.refuse(c.span, construct);
        };
        if c.arguments.len() < min || c.arguments.len() > max {
            let construct = format!("argument count for {object}.{method}");
            return self.refuse(c.span, construct);
        }
        // J87-3: `Math.max(...xs)` / `Math.min(...xs)` spread an array PROVEN to be a list (a
        // Python `*` over anything else, a dict's keys say, is not JS's iterator).
        if object == "Math" && (method == "max" || method == "min") {
            let mut codes = Vec::new();
            for arg in &c.arguments {
                match arg {
                    Argument::SpreadElement(spread) => {
                        let value = self.expr(&spread.argument);
                        if !value.is_list {
                            return self
                                .refuse(spread.span, "spread of a value not proven an array");
                        }
                        codes.push(format!("*{}", value.at(ATOM)));
                    }
                    other => {
                        let e = other.as_expression().expect("not a spread");
                        codes.push(self.expr(e).code);
                    }
                }
            }
            return returned(ret, format!("{helper}({})", codes.join(", ")));
        }
        let Some(args) = self.args(&c.arguments, None, false) else {
            return Py::atom("None");
        };
        returned(ret, format!("{helper}({})", args.join(", ")))
    }

    fn new_expr(&mut self, n: &NewExpression<'_>) -> Py {
        let Expression::Identifier(id) = strip(&n.callee) else {
            let construct = format!("new {}", self.text(n.callee.span()));
            return self.refuse(n.span, construct);
        };
        let name = id.name.as_str();
        let shadowed = self.scopes.iter().any(|s| s.contains(name));
        let class: Option<String> = if let Some(py) = self.classes.get(name).filter(|_| !shadowed) {
            Some(py.clone())
        } else if self.is_local(name) {
            None
        } else {
            match name {
                "Map" | "Set" => {
                    if n.arguments.len() > 1 {
                        return self.refuse(n.span, "argument count for new Map/Set");
                    }
                    Some(if name == "Map" { "_JsMap" } else { "_JsSet" }.to_string())
                }
                // J86: the built-in Errors the codec throws.
                "Error" | "TypeError" => {
                    if n.arguments.len() > 1 {
                        return self.refuse(n.span, "argument count for new Error");
                    }
                    Some(
                        if name == "Error" {
                            "_JsError"
                        } else {
                            "_JsTypeError"
                        }
                        .to_string(),
                    )
                }
                "RegExp" => return self.dynamic_regex(n),
                _ => match adapters::global(name) {
                    Some(adapter) if matches!(adapter.kind, AdapterKind::Class(_)) => {
                        self.imports
                            .entry(self.ctx.adapter_module.clone())
                            .or_default()
                            .insert(adapter.py_name.to_string());
                        Some(adapter.py_name.to_string())
                    }
                    _ => None,
                },
            }
        };
        let Some(class) = class else {
            let construct = format!("new {}", self.text(n.callee.span()));
            return self.refuse(n.span, construct);
        };
        let Some(args) = self.args(&n.arguments, None, false) else {
            return Py::atom("None");
        };
        Py::atom(format!("{class}({})", args.join(", ")))
    }

    /// `new RegExp(`...`)` (J86): a template literal whose every substitution is a whole `{n}`
    /// repeat count, so the pattern is checked against the whitelist grammar at compile time and
    /// only the count is supplied at run time (`_js_regexp_dynamic` checks it is an integer).
    fn dynamic_regex(&mut self, n: &NewExpression<'_>) -> Py {
        let template = match n.arguments.as_slice() {
            [arg] => match arg.as_expression().map(strip) {
                Some(Expression::TemplateLiteral(t)) => t,
                _ => return self.refuse(n.span, "new RegExp of anything but a template literal"),
            },
            _ => return self.refuse(n.span, "new RegExp with flags"),
        };
        let mut source = String::new();
        for (i, quasi) in template.quasis.iter().enumerate() {
            match quasi
                .value
                .cooked
                .and_then(|c| c.as_str().map(str::to_string))
            {
                Some(text) => source.push_str(&text),
                None => return self.refuse(quasi.span, "template escape"),
            }
            if i + 1 < template.quasis.len() {
                source.push(REGEX_HOLE);
            }
        }
        let translated = match translate_regex(&source) {
            Ok(pattern) => pattern,
            Err(why) => return self.refuse(n.span, why),
        };
        let mut parts = Vec::new();
        for (i, piece) in translated.split(REGEX_HOLE).enumerate() {
            if i > 0 {
                let value = self.expr(&template.expressions[i - 1]);
                parts.push(value.code);
            }
            parts.push(py_str(piece));
        }
        Py::atom(format!("_js_regexp_dynamic({})", parts.join(", ")))
    }

    fn regex(&mut self, r: &RegExpLiteral<'_>) -> Py {
        // J86: `g` is the one flag accepted (only `.replace` takes a `g` regex at run time).
        let global = r.regex.flags == RegExpFlags::G;
        if !r.regex.flags.is_empty() && !global {
            return self.refuse(r.span, "regex flags other than g");
        }
        let pattern = match translate_regex(r.regex.pattern.text.as_str()) {
            Ok(pattern) => pattern,
            Err(why) => return self.refuse(r.span, why),
        };
        let key = (pattern, global);
        let index = match self.regexes.iter().position(|p| *p == key) {
            Some(i) => i,
            None => {
                self.regexes.push(key);
                self.regexes.len() - 1
            }
        };
        Py {
            pure: true,
            is_regex: !global,
            ..Py::atom(format!("_JS_RE_{index}"))
        }
    }
}

// -------------------------------------------------------------------- J86: modules and classes

impl<'s> Lowerer<'s> {
    /// A value import: from a compiled module (`from .<module> import <names>`), or through the
    /// adapter seam (`adapters.rs`). Anything else is refused, naming the import.
    fn import(&mut self, i: &ImportDeclaration<'_>) {
        if i.import_kind.is_type() {
            return;
        }
        let Some(spec) = i.source.value.as_str() else {
            self.refuse(i.span, "import specifier with a lone surrogate");
            return;
        };
        let Some(specifiers) = &i.specifiers else {
            self.refuse(i.span, "side-effect import");
            return;
        };
        let resolved = resolve_specifier(&self.ctx.path, spec);
        for specifier in specifiers {
            let ImportDeclarationSpecifier::ImportSpecifier(s) = specifier else {
                self.refuse(specifier.span(), "default or namespace import");
                continue;
            };
            if s.import_kind.is_type() {
                continue;
            }
            let imported = s.imported.name();
            if imported != s.local.name {
                self.refuse(s.span, "renamed import");
                continue;
            }
            let local = s.local.name.as_str();
            let compiled = resolved
                .as_ref()
                .and_then(|path| self.ctx.modules.get(path))
                .cloned();
            if let Some(module) = compiled {
                let Some((py, is_class)) = module.names.get(local).cloned() else {
                    let construct =
                        format!("import of {local} from {spec}, which that module does not export");
                    self.refuse(s.span, construct);
                    continue;
                };
                self.claim(local, &py, s.span);
                self.imports
                    .entry(format!(".{}", module.py_module))
                    .or_default()
                    .insert(py.clone());
                self.globals.insert(local.to_string(), py.clone());
                if is_class {
                    self.classes.insert(local.to_string(), py);
                }
                continue;
            }
            match resolved
                .as_deref()
                .and_then(|path| adapters::import(path, local))
            {
                Some(adapter) => {
                    let py = adapter.py_name.to_string();
                    self.claim(local, &py, s.span);
                    self.imports
                        .entry(self.ctx.adapter_module.clone())
                        .or_default()
                        .insert(py.clone());
                    self.globals.insert(local.to_string(), py.clone());
                    match adapter.kind {
                        AdapterKind::Class(_) => {
                            self.classes.insert(local.to_string(), py);
                        }
                        // J87-3: an adapter Error class a compiled class may extend.
                        AdapterKind::ErrorClass => {
                            self.classes.insert(local.to_string(), py);
                            self.error_classes.insert(local.to_string());
                        }
                        AdapterKind::Function => {
                            self.adapter_fns.insert(local.to_string());
                        }
                    }
                }
                None => {
                    let construct = format!(
                        "import of {local} from {spec}: no compiled module and no declared adapter"
                    );
                    self.refuse(s.span, construct);
                    // Bound anyway, so each use is not refused again as an unknown global.
                    self.globals
                        .insert(local.to_string(), py_name(local, true, false));
                }
            }
        }
    }

    /// `export { a, b }`: each a module-level name (declared or imported), exported as itself.
    fn export_list(&mut self, e: &ExportNamedDeclaration<'_>) {
        for specifier in &e.specifiers {
            if specifier.export_kind.is_type() {
                continue;
            }
            let local = specifier.local.name();
            if specifier.exported.name() != local {
                self.refuse(specifier.span, "renamed export");
                continue;
            }
            match self.globals.get(local.as_str()) {
                Some(py) => {
                    if !self.exports.contains(py) {
                        self.exports.push(py.clone());
                    }
                }
                None => {
                    self.refuse(specifier.span, "export of a name this module does not bind");
                }
            }
        }
    }

    /// A class: a Python class over `_JsObject` (or `_JsError` for `extends Error`). Fields are
    /// initialised in declaration order at the start of `__init__` (after the base's, as JS does
    /// for a derived class), then the constructor body runs.
    fn class_decl(&mut self, c: &Class<'_>, out: &mut Vec<String>) {
        let Some(id) = &c.id else {
            self.refuse(c.span, "anonymous class");
            return;
        };
        let name = self.classes[id.name.as_str()].clone();
        if !c.decorators.is_empty() {
            self.refuse(c.span, "decorator");
        }
        if c.r#abstract {
            self.refuse(c.span, "abstract class");
        }
        // J87-3: `extends` an Error class visible here (an adapter `ErrorClass` such as
        // `BantamError`, or one declared above) as well as `Error` itself.
        let error_base: Option<String> = match &c.heritage {
            None => None,
            Some(h) => match strip(&h.expression) {
                Expression::Identifier(base) if base.name == "Error" && !self.is_local("Error") => {
                    Some("_JsError".to_string())
                }
                Expression::Identifier(base)
                    if self.error_classes.contains(base.name.as_str())
                        && !self.is_scoped(base.name.as_str()) =>
                {
                    Some(self.classes[base.name.as_str()].clone())
                }
                other => {
                    self.refuse(other.span(), "extends anything but an Error class");
                    return;
                }
            },
        };
        let is_error = error_base.is_some();
        if is_error {
            self.error_classes.insert(id.name.to_string());
        }
        let base = error_base.as_deref().unwrap_or("_JsObject");

        let mut fields: Vec<&PropertyDefinition<'_>> = Vec::new();
        let mut methods: Vec<&MethodDefinition<'_>> = Vec::new();
        let mut constructor: Option<&MethodDefinition<'_>> = None;
        let mut own: BTreeSet<String> = BTreeSet::new();
        let mut own_methods: BTreeSet<String> = BTreeSet::new();
        for element in &c.body.body {
            match element {
                ClassElement::PropertyDefinition(p) => {
                    if p.r#static || p.computed || p.declare || !p.decorators.is_empty() {
                        self.refuse(p.span, "static, computed or declared class field");
                        continue;
                    }
                    let Some(key) = self.member_name(&p.key, p.span, is_error) else {
                        continue;
                    };
                    own.insert(key);
                    fields.push(p);
                }
                ClassElement::MethodDefinition(m) => {
                    if m.r#static || m.computed || !m.decorators.is_empty() {
                        self.refuse(m.span, "static or computed method");
                        continue;
                    }
                    if m.value.generator || m.value.r#async {
                        self.refuse(m.span, "generator or async method");
                        continue;
                    }
                    if m.value.body.is_none() {
                        self.refuse(m.span, "method overload signature");
                        continue;
                    }
                    match m.kind {
                        MethodDefinitionKind::Constructor => {
                            if is_error {
                                self.refuse(m.span, "constructor in a class that extends Error");
                                continue;
                            }
                            constructor = Some(m);
                        }
                        MethodDefinitionKind::Method | MethodDefinitionKind::Get => {
                            let Some(key) = self.member_name(&m.key, m.span, is_error) else {
                                continue;
                            };
                            if !own.insert(key.clone()) {
                                self.refuse(m.span, "duplicate class member");
                                continue;
                            }
                            if m.kind == MethodDefinitionKind::Method {
                                own_methods.insert(key);
                            }
                            methods.push(m);
                        }
                        MethodDefinitionKind::Set => {
                            self.refuse(m.span, "setter");
                        }
                    }
                }
                other => {
                    self.refuse(other.span(), "class member");
                }
            }
        }

        let mut ctx = ClassCtx::default();
        ctx.members.extend(own.iter().cloned());
        ctx.methods.extend(own_methods.iter().cloned());
        if is_error {
            for member in ["message", "name", "toString"] {
                ctx.members.insert(member.to_string());
            }
            ctx.methods.insert("toString".to_string());
        }
        let saved = self.class_ctx.replace(ctx);

        let set = |names: &BTreeSet<String>| -> String {
            if names.is_empty() {
                "frozenset()".to_string()
            } else {
                let items: Vec<String> = names.iter().map(|n| py_str(n)).collect();
                format!("frozenset({{{}}})", items.join(", "))
            }
        };
        out.push(format!("class {name}({base}):"));
        out.push(format!("    _js_name = {}", py_str(id.name.as_str())));
        out.push(format!("    _js_own = {}", set(&own)));
        out.push(format!("    _js_own_methods = {}", set(&own_methods)));

        // __init__: base, then fields, then the constructor body.
        if !fields.is_empty() || constructor.is_some() || !is_error {
            out.push(String::new());
            let (params, locals, body): (Vec<(String, String)>, HashSet<String>, &[Statement<'_>]) =
                match constructor {
                    Some(ctor) => {
                        let names = self.params(&ctor.value.params);
                        let mut locals: HashSet<String> =
                            names.iter().map(|(src, _)| src.clone()).collect();
                        let statements: &[Statement<'_>] = ctor
                            .value
                            .body
                            .as_ref()
                            .map_or(&[], |b| b.statements.as_slice());
                        let mut stack = vec![locals.clone()];
                        self.collect_block(statements, &mut stack, &mut locals);
                        (names, locals, statements)
                    }
                    None => (Vec::new(), HashSet::new(), &[]),
                };
            let mut signature = vec!["self".to_string()];
            signature.extend(params.iter().map(|(_, py)| py.clone()));
            // Extra constructor arguments are ignored in JS.
            signature.push("*_".to_string());
            if is_error && constructor.is_none() {
                out.push("    def __init__(self, *args):".to_string());
                out.push(format!("        {base}.__init__(self, *args)"));
            } else {
                out.push(format!("    def __init__({}):", signature.join(", ")));
            }
            let owner = constructor.map_or(c.span.start, |ctor| ctor.span.start);
            self.push_scope(locals, owner);
            self.rets.push(None);
            if let Some(ctor) = constructor {
                self.bind_params(&ctor.value.params, &[]);
                self.param_defaults(&ctor.value.params, 2, out);
                self.hoist_params(&ctor.value.params, 2, out);
            }
            for field in &fields {
                let key = property_key_name(&field.key).expect("checked by member_name");
                let value = match &field.value {
                    Some(init) => self.expr(init).code,
                    // ES2022 class fields: a declared field is an own property holding undefined.
                    None => "_JS_UNDEFINED".to_string(),
                };
                out.push(format!("        self.{key} = {value}"));
            }
            self.block(body, 2, out);
            if fields.is_empty() && body.is_empty() && !(is_error && constructor.is_none()) {
                out.push("        pass".to_string());
            }
            self.rets.pop();
            self.pop_scope();
        }

        for m in methods {
            let key = property_key_name(&m.key).expect("checked by member_name");
            let f = &m.value;
            let statements: &[Statement<'_>] =
                f.body.as_ref().map_or(&[], |b| b.statements.as_slice());
            let names = self.params(&f.params);
            let mut locals: HashSet<String> = names.iter().map(|(src, _)| src.clone()).collect();
            let mut stack = vec![locals.clone()];
            self.collect_block(statements, &mut stack, &mut locals);
            self.push_scope(locals, m.span.start);
            self.rets.push(None);
            self.bind_params(&f.params, &[]);
            out.push(String::new());
            if m.kind == MethodDefinitionKind::Get {
                if !names.is_empty() {
                    self.refuse(m.span, "getter with parameters");
                }
                out.push("    @property".to_string());
            }
            let mut signature = vec!["self".to_string()];
            signature.extend(names.iter().map(|(_, py)| py.clone()));
            out.push(format!("    def {key}({}):", signature.join(", ")));
            self.param_defaults(&f.params, 2, out);
            self.hoist_params(&f.params, 2, out);
            self.block(statements, 2, out);
            if !ends_in_exit(statements) {
                out.push("        return _JS_UNDEFINED".to_string());
            }
            self.rets.pop();
            self.pop_scope();
        }
        self.class_ctx = saved;
    }

    /// A class member's name, which is also its Python attribute: a plain identifier that is not a
    /// Python keyword, not `_`-prefixed (the runtime's own attributes are), and for an Error
    /// subclass not one of the attributes Python's exceptions already carry.
    fn member_name(&mut self, key: &PropertyKey<'_>, span: Span, is_error: bool) -> Option<String> {
        let Some(name) = property_key_name(key) else {
            self.refuse(span, "class member key");
            return None;
        };
        if is_py_keyword(&name)
            || name.starts_with('_')
            || (is_error && matches!(name.as_str(), "args" | "with_traceback" | "add_note"))
        {
            let construct = format!("class member named {name}");
            self.refuse(span, construct);
            return None;
        }
        Some(name)
    }

    /// `this.<name>` inside a class: the attribute, which the class (or Error) must declare.
    /// Whether `object.name` names a method (J86-R finding 3). On `this` the class decides
    /// exactly; on any other receiver the name does (`JS_METHOD_NAMES`, `METHODS`, every class).
    fn is_method_name(&self, object: &Expression<'_>, name: &str) -> bool {
        if let Expression::ThisExpression(_) = strip(object) {
            return self
                .class_ctx
                .as_ref()
                .is_some_and(|class| class.methods.contains(name));
        }
        JS_METHOD_NAMES.contains(&name)
            || METHODS.iter().any(|(m, ..)| *m == name)
            || self.ctx.class_methods.contains(name)
    }

    fn this_member(&mut self, name: &str, span: Span) -> Py {
        let declared = self
            .class_ctx
            .as_ref()
            .map(|class| class.members.contains(name));
        match declared {
            None => self.refuse(span, "this outside a class"),
            Some(false) => {
                let construct = format!("this.{name} for a member the class does not declare");
                self.refuse(span, construct)
            }
            Some(true) => Py::atom(format!("self.{name}")),
        }
    }

    /// The Python class an `instanceof` right-hand side names, if it is a compiled class or one of
    /// the built-in Errors.
    fn class_ref(&mut self, e: &Expression<'_>) -> Option<String> {
        let Expression::Identifier(id) = strip(e) else {
            return None;
        };
        let name = id.name.as_str();
        if self.scopes.iter().any(|s| s.contains(name)) {
            return None;
        }
        if let Some(py) = self.classes.get(name) {
            return Some(py.clone());
        }
        match name {
            "Error" if !self.is_local(name) => Some("_JsError".to_string()),
            "TypeError" if !self.is_local(name) => Some("_JsTypeError".to_string()),
            _ => None,
        }
    }

    /// `throw new X(...)` with X a class or a built-in Error: raised as itself.
    fn is_error_construction(&mut self, e: &Expression<'_>) -> bool {
        match strip(e) {
            Expression::NewExpression(n) => {
                let class = self.class_ref(&n.callee);
                class.is_some()
            }
            _ => false,
        }
    }

    // ---------------------------------------------------------------- J86: closures

    /// `const f = (...) => ...` inside a function: a nested `def`, which closes over the enclosing
    /// function's locals as the arrow does; one it assigns is declared `nonlocal`. Refused inside
    /// a loop, where JS gives each iteration its own binding and Python would share one.
    fn nested_def(
        &mut self,
        name: &str,
        a: &ArrowFunctionExpression<'_>,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        if a.r#async {
            self.refuse(a.span, "async function");
            return;
        }
        if self.breaks.contains(&BreakTarget::Loop) {
            self.refuse(a.span, "function defined inside a loop");
            return;
        }
        let names = self.params(&a.params);
        let mut locals: HashSet<String> = names.iter().map(|(src, _)| src.clone()).collect();
        if let ArrowFunctionBody::FunctionBody(body) = &a.body {
            let mut stack = vec![locals.clone()];
            self.collect_block(&body.statements, &mut stack, &mut locals);
        }
        self.push_scope(locals, a.span.start);
        self.rets.push(None);
        self.bind_params(&a.params, &[]);
        self.defs.push((self.scopes.len() - 1, BTreeSet::new()));
        let saved_breaks = std::mem::take(&mut self.breaks);
        let mut body_out = Vec::new();
        self.param_defaults(&a.params, indent + 1, &mut body_out);
        self.hoist_params(&a.params, indent + 1, &mut body_out);
        match &a.body {
            ArrowFunctionBody::FunctionBody(body) => {
                self.block(&body.statements, indent + 1, &mut body_out);
                if !ends_in_exit(&body.statements) {
                    body_out.push(format!("{}return _JS_UNDEFINED", pad(indent + 1)));
                }
            }
            other => {
                let expr = other
                    .as_expression()
                    .expect("an arrow body is a block or an expression");
                let value = self.expr(expr);
                body_out.push(format!("{}return {}", pad(indent + 1), value.code));
            }
        }
        self.breaks = saved_breaks;
        let (_, nonlocals) = self.defs.pop().expect("pushed above");
        self.rets.pop();
        self.pop_scope();
        out.push(format!(
            "{}def {name}({}):",
            pad(indent),
            join_params(&names)
        ));
        if !nonlocals.is_empty() {
            let names: Vec<String> = nonlocals.iter().map(|n| py_name(n, false, false)).collect();
            out.push(format!("{}nonlocal {}", pad(indent + 1), names.join(", ")));
        }
        out.extend(body_out);
    }

    /// An assignment target that is a name: it must be a local (a module-level binding is a
    /// `const` or an import, both read-only in JS); one that belongs to an enclosing function is
    /// noted for `nonlocal`.
    fn local_target(&mut self, name: &str, span: Span) -> Py {
        let Some(index) = self.scopes.iter().rposition(|s| s.contains(name)) else {
            return self.refuse(span, "assignment to a module-level name");
        };
        if let Some((start, nonlocals)) = self.defs.last_mut()
            && index < *start
        {
            nonlocals.insert(name.to_string());
        }
        // J87: an assignment rebinds the name, so its UTF-16 view may not be hoisted; a compound
        // assignment reads the target first, so it carries the binding's facts.
        if let Some(key) = self.var_key(name) {
            self.observed.assigned.insert(key);
        }
        let target = Py::atom(py_name(name, false, false));
        self.with_binding_facts(name, target)
    }

    /// The value of `target = right` or `target op= right`.
    fn assigned_value(
        &mut self,
        op: Option<BinaryOperator>,
        target: Py,
        right: &Expression<'_>,
    ) -> Py {
        let value = self.expr(right);
        match op {
            None => value,
            Some(op) => arith(op, target, value),
        }
    }

    // ---------------------------------------------------------------- J86: destructuring

    /// `const [a, , b] = e`: through the iterator (`_js_destructure`), so a string gives code points,
    /// a short array reads `undefined`, and `null` is a TypeError.
    fn array_pattern_decl(
        &mut self,
        a: &ArrayPattern<'_>,
        init: Option<&Expression<'_>>,
        span: Span,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        let Some(init) = init else {
            self.refuse(span, "destructuring declaration without initializer");
            return;
        };
        if a.rest.is_some() {
            self.refuse(a.span, "destructuring rest element");
            return;
        }
        let mut names = Vec::new();
        for element in &a.elements {
            match element {
                Some(BindingPattern::BindingIdentifier(id)) => {
                    names.push(py_name(id.name.as_str(), false, false))
                }
                None => names.push("_".to_string()),
                Some(other) => {
                    self.refuse(other.span(), "nested or defaulted destructuring");
                    return;
                }
            }
        }
        if names.iter().all(|n| n == "_") {
            self.refuse(a.span, "destructuring that binds nothing");
            return;
        }
        let value = self.expr(init);
        let sources: Vec<Option<&str>> = a
            .elements
            .iter()
            .map(|e| match e {
                Some(BindingPattern::BindingIdentifier(id)) => Some(id.name.as_str()),
                _ => None,
            })
            .collect();
        let line = self.destructured(&names, &sources, value);
        out.push(format!("{}{line}", pad(indent)));
    }

    /// J87: `<names> = <value>` through the iterator, binding each name to what the value proves of
    /// its position; a fresh array of exactly that many items unpacks directly.
    fn destructured(&mut self, names: &[String], sources: &[Option<&str>], value: Py) -> String {
        let tuple = value.tuple.clone();
        for (i, source) in sources.iter().enumerate() {
            if let Some(source) = source {
                let fact = if value.top {
                    Fact::top()
                } else {
                    tuple
                        .as_ref()
                        .and_then(|t| t.get(i).cloned())
                        .unwrap_or_default()
                };
                self.bind(source, fact);
            }
        }
        match tuple {
            Some(t) if t.len() == names.len() && names.len() > 1 => {
                format!("{} = {}", names.join(", "), value.code)
            }
            _ => format!(
                "{} = _js_destructure({}, {})",
                unpack_target(names),
                value.code,
                names.len()
            ),
        }
    }

    /// `const { a, b: c } = e`: one `_js_get` per property (a TypeError on `null`/`undefined`).
    fn object_pattern_decl(
        &mut self,
        o: &ObjectPattern<'_>,
        init: Option<&Expression<'_>>,
        span: Span,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        let Some(init) = init else {
            self.refuse(span, "destructuring declaration without initializer");
            return;
        };
        if o.rest.is_some() || o.properties.is_empty() {
            self.refuse(
                o.span,
                "object destructuring with a rest element or nothing to bind",
            );
            return;
        }
        let value = self.expr(init);
        let source = if value.pure {
            value.code
        } else {
            let tmp = format!("_js_obj{}", self.tmp);
            self.tmp += 1;
            out.push(format!("{}{tmp} = {}", pad(indent), value.code));
            tmp
        };
        for property in &o.properties {
            let (Some(key), false, BindingPattern::BindingIdentifier(id)) = (
                property_key_name(&property.key),
                property.computed,
                &property.value,
            ) else {
                self.refuse(property.span, "nested, computed or defaulted destructuring");
                continue;
            };
            self.bind(id.name.as_str(), Fact::default());
            out.push(format!(
                "{}{} = _js_get({source}, {})",
                pad(indent),
                py_name(id.name.as_str(), false, false),
                py_str(&key)
            ));
        }
    }

    /// `[a, b] = e` (an expression statement): as the declaration, into existing locals.
    fn array_assignment(
        &mut self,
        t: &ArrayAssignmentTarget<'_>,
        right: &Expression<'_>,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        if t.rest.is_some() {
            self.refuse(t.span, "destructuring rest element");
            return;
        }
        let mut names = Vec::new();
        let mut sources: Vec<Option<&str>> = Vec::new();
        for element in &t.elements {
            match element {
                Some(AssignmentTargetMaybeDefault::AssignmentTargetIdentifier(id)) => {
                    let target = self.local_target(id.name.as_str(), id.span);
                    names.push(target.code);
                    sources.push(Some(id.name.as_str()));
                }
                None => {
                    names.push("_".to_string());
                    sources.push(None);
                }
                Some(other) => {
                    self.refuse(other.span(), "destructuring assignment target");
                    return;
                }
            }
        }
        let value = self.expr(right);
        let line = self.destructured(&names, &sources, value);
        out.push(format!("{}{line}", pad(indent)));
    }

    // ---------------------------------------------------------------- J86: switch

    /// `switch` as an if-chain over `===` on the discriminant, evaluated once. Every case group must
    /// end its body (return, throw, or a trailing `break`, which is dropped); a case that falls
    /// into the next one other than by being empty is refused, and so is a `default` that is not
    /// last.
    fn switch(&mut self, sw: &SwitchStatement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        let discriminant = self.expr(&sw.discriminant);
        let subject = if discriminant.pure && discriminant.prec == ATOM {
            discriminant
        } else {
            let tmp = format!("_js_switch{}", self.tmp);
            self.tmp += 1;
            out.push(format!("{p}{tmp} = {}", discriminant.code));
            Py {
                pure: true,
                is_bool: discriminant.is_bool,
                is_num: discriminant.is_num,
                is_double: discriminant.is_double,
                is_str: discriminant.is_str,
                ..Py::atom(tmp)
            }
        };
        let mut pending: Vec<&Expression<'_>> = Vec::new();
        let mut first = true;
        let count = sw.cases.len();
        for (index, case) in sw.cases.iter().enumerate() {
            let Some(test) = &case.test else {
                if index + 1 != count || !pending.is_empty() {
                    self.refuse(
                        case.span,
                        "default that is not the last, separate switch case",
                    );
                    return;
                }
                if first {
                    // A switch with only a default: its body runs unconditionally.
                    self.case_body(&case.consequent, case.span, indent, out);
                } else {
                    out.push(format!("{p}else:"));
                    self.case_body(&case.consequent, case.span, indent + 1, out);
                }
                return;
            };
            pending.push(test);
            if case.consequent.is_empty() {
                if index + 1 == count {
                    self.refuse(case.span, "empty last switch case");
                }
                continue;
            }
            let mut tests = Vec::new();
            for test in std::mem::take(&mut pending) {
                let value = self.expr(test);
                tests.push(
                    self.strict_eq_py(subject.clone(), value, test, false)
                        .at(OR + 1),
                );
            }
            let keyword = if first { "if" } else { "elif" };
            first = false;
            out.push(format!("{p}{keyword} {}:", tests.join(" or ")));
            self.case_body(&case.consequent, case.span, indent + 1, out);
        }
    }

    fn case_body(
        &mut self,
        body: &[Statement<'_>],
        span: Span,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        let statements = match body.last() {
            Some(Statement::BreakStatement(b)) if b.label.is_none() => &body[..body.len() - 1],
            _ if ends_in_exit(body) => body,
            _ => {
                self.refuse(span, "switch case that falls through");
                return;
            }
        };
        self.breaks.push(BreakTarget::Switch);
        let start = out.len();
        for s in statements {
            self.stmt(s, indent, out);
        }
        if out.len() == start {
            out.push(format!("{}pass", pad(indent)));
        }
        self.breaks.pop();
    }
}

/// `a, b` / `[a]` as a Python unpacking target.
fn unpack_target(names: &[String]) -> String {
    if names.len() == 1 {
        format!("[{}]", names[0])
    } else {
        names.join(", ")
    }
}

/// A non-computed property key's name (`a`, `'a'`), if it is a plain one.
fn property_key_name(key: &PropertyKey<'_>) -> Option<String> {
    match key {
        PropertyKey::StaticIdentifier(id) => Some(id.name.to_string()),
        PropertyKey::StringLiteral(s) => s.value.as_str().map(str::to_string),
        _ => None,
    }
    .filter(|name| {
        let mut chars = name.chars();
        chars
            .next()
            .is_some_and(|c| c.is_ascii_alphabetic() || c == '_' || c == '$')
            && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
            && !name.contains('$')
    })
}

/// A relative import specifier resolved against the importing module's path, `.js` read as the
/// `.ts` it is compiled from (`runtime-ts/src/memory/pyyaml.ts`). None for a bare specifier.
pub fn resolve_specifier(importer: &str, spec: &str) -> Option<String> {
    // J87-3: a Node builtin (`node:fs`) is its own key in the adapter table.
    if spec.starts_with("node:") {
        return Some(spec.to_string());
    }
    if !(spec.starts_with("./") || spec.starts_with("../")) {
        return None;
    }
    let mut parts: Vec<&str> = importer.split('/').collect();
    parts.pop();
    for piece in spec.split('/') {
        match piece {
            "." | "" => {}
            ".." => {
                parts.pop()?;
            }
            other => parts.push(other),
        }
    }
    let joined = parts.join("/");
    Some(match joined.strip_suffix(".js") {
        Some(stem) => format!("{stem}.ts"),
        None => joined,
    })
}

/// What one module exports (source name -> (Python name, is a class)) and the method names its
/// classes declare, read off the AST before anything is lowered, so another module can import it.
pub fn scan_module(program: &Program<'_>) -> (HashMap<String, (String, bool)>, HashSet<String>) {
    let mut exports = HashMap::new();
    let mut methods = HashSet::new();
    let mut locals: HashMap<String, (String, bool)> = HashMap::new();
    for stmt in &program.body {
        let (decl, exported) = match stmt {
            Statement::ExportDeclaration(e) => (Some(&e.declaration), true),
            _ => (stmt.as_declaration(), false),
        };
        let Some(decl) = decl else { continue };
        let mut bind = |name: &str, entry: (String, bool)| {
            locals.insert(name.to_string(), entry.clone());
            if exported {
                exports.insert(name.to_string(), entry);
            }
        };
        match decl {
            Declaration::FunctionDeclaration(f) => {
                if let Some(id) = &f.id {
                    bind(
                        id.name.as_str(),
                        (py_name(id.name.as_str(), true, !exported), false),
                    );
                }
            }
            Declaration::VariableDeclaration(v) => {
                for d in &v.declarations {
                    if let BindingPattern::BindingIdentifier(id) = &d.id {
                        bind(
                            id.name.as_str(),
                            (py_name(id.name.as_str(), true, !exported), false),
                        );
                    }
                }
            }
            Declaration::ClassDeclaration(c) => {
                if let Some(id) = &c.id {
                    bind(
                        id.name.as_str(),
                        (class_py_name(id.name.as_str(), exported), true),
                    );
                }
                for element in &c.body.body {
                    if let ClassElement::MethodDefinition(m) = element
                        && m.kind == MethodDefinitionKind::Method
                        && let Some(name) = property_key_name(&m.key)
                    {
                        methods.insert(name);
                    }
                }
            }
            _ => {}
        }
    }
    for stmt in &program.body {
        if let Statement::ExportNamedDeclaration(e) = stmt {
            for specifier in &e.specifiers {
                let name = specifier.local.name().to_string();
                if let Some(entry) = locals.get(&name) {
                    exports.insert(name, entry.clone());
                }
            }
        }
    }
    (exports, methods)
}

// -------------------------------------------------------------------- helpers

/// J87: the Python name of a hoisted UTF-16 view (`_jsu_` is neither a runtime name, which all
/// start `_js_`, `_Js` or `_JS_`, nor a source one, which may not start `_js`).
fn units_name(name: &str) -> String {
    format!("_jsu_{}", py_name(name, false, false))
}

fn method_as_value(name: &str) -> String {
    format!("method .{name} read as a value (a method may only be called directly)")
}

fn pad(indent: usize) -> String {
    "    ".repeat(indent)
}

fn join_params(names: &[(String, String)]) -> String {
    names
        .iter()
        .map(|(_, py)| py.as_str())
        .collect::<Vec<_>>()
        .join(", ")
}

/// `value` as a JS double holds it (SUBSET.md, Numbers): wrapped in `_js_num` unless it already is.
fn js_num(value: Py) -> Py {
    if value.is_double || value.is_str {
        value
    } else {
        Py {
            is_num: value.is_num,
            is_double: true,
            pure: value.pure,
            ..Py::atom(format!("_js_num({})", value.code))
        }
    }
}

/// `left <op> right` for `+ - * / %`, from lowered operands (shared by `a op b` and `a op= b`).
/// J87: the result of an optimistic operand is optimistic (`types::Fact::top`).
fn arith(op: BinaryOperator, left: Py, right: Py) -> Py {
    let optimistic = left.top || right.top;
    let result = arith_of(op, left, right);
    if optimistic {
        result.with_fact(None)
    } else {
        result
    }
}

fn arith_of(op: BinaryOperator, left: Py, right: Py) -> Py {
    use BinaryOperator as Op;
    match op {
        Op::Subtraction => {
            let (left, right) = (js_num(left), js_num(right));
            rounded(format!("{} - {}", left.at(ADD), right.at(ADD + 1)))
        }
        Op::Addition => {
            if left.is_num && right.is_num {
                let (left, right) = (js_num(left), js_num(right));
                rounded(format!("{} + {}", left.at(ADD), right.at(ADD + 1)))
            } else if left.is_str && right.is_str {
                // J86: a lead surrogate ending `left` and a trail surrogate starting `right` form
                // one character in JS; `_js_cat` joins them unless either end is known safe.
                let code = if left.safe_end || right.safe_start {
                    format!("{} + {}", left.at(ADD), right.at(ADD + 1))
                } else {
                    format!("_js_cat({}, {})", left.code, right.code)
                };
                let prec = if code.starts_with("_js_cat(") {
                    ATOM
                } else {
                    ADD
                };
                Py {
                    is_str: true,
                    safe_start: left.safe_start,
                    safe_end: right.safe_end,
                    ..Py::new(code, prec)
                }
            } else {
                Py::atom(format!("_js_add({}, {})", left.code, right.code))
            }
        }
        other => {
            // J86: `*`, `/`, `%` through the runtime: doubles (with -0, Infinity and NaN where JS
            // has them) or two BigInts exactly; a mix is the TypeError JS raises.
            let helper = match other {
                Op::Multiplication => "_js_mul",
                Op::Division => "_js_div",
                _ => "_js_mod",
            };
            Py {
                is_num: left.is_num && right.is_num,
                is_double: true,
                ..Py::atom(format!("{helper}({}, {})", left.code, right.code))
            }
        }
    }
}

fn is_lead(unit: u16) -> bool {
    (0xd800..=0xdbff).contains(&unit)
}

fn is_trail(unit: u16) -> bool {
    (0xdc00..=0xdfff).contains(&unit)
}

/// The statement list cannot run off its end: its last statement returns or throws (through
/// blocks, and an `if` whose both arms exit).
fn ends_in_exit(stmts: &[Statement<'_>]) -> bool {
    stmts.last().is_some_and(exits)
}

fn exits(s: &Statement<'_>) -> bool {
    match s {
        Statement::ReturnStatement(_) | Statement::ThrowStatement(_) => true,
        Statement::BlockStatement(b) => ends_in_exit(&b.body),
        // J87-3: both the block and the handler exit (a `finally` is refused).
        Statement::TryStatement(t) => {
            t.finalizer.is_none()
                && ends_in_exit(&t.block.body)
                && t.handler
                    .as_ref()
                    .is_some_and(|h| ends_in_exit(&h.body.body))
        }
        Statement::IfStatement(i) => {
            exits(&i.consequent) && i.alternate.as_ref().is_some_and(exits)
        }
        _ => false,
    }
}

/// J87-3: a `continue` in `s` that continues the loop `s` is the body of (not one inside a nested
/// loop, whose own `continue` it is).
fn continues_out(s: &Statement<'_>) -> bool {
    match s {
        Statement::ContinueStatement(_) => true,
        Statement::BlockStatement(b) => b.body.iter().any(continues_out),
        Statement::IfStatement(i) => {
            continues_out(&i.consequent) || i.alternate.as_ref().is_some_and(continues_out)
        }
        Statement::LabeledStatement(l) => continues_out(&l.body),
        Statement::SwitchStatement(sw) => sw
            .cases
            .iter()
            .any(|case| case.consequent.iter().any(continues_out)),
        Statement::TryStatement(t) => {
            t.block.body.iter().any(continues_out)
                || t.handler
                    .as_ref()
                    .is_some_and(|h| h.body.body.iter().any(continues_out))
                || t.finalizer
                    .as_ref()
                    .is_some_and(|f| f.body.iter().any(continues_out))
        }
        _ => false,
    }
}

/// A class's Python name: as written when exported, `_` + name otherwise (J86).
pub fn class_py_name(name: &str, exported: bool) -> String {
    if exported {
        name.to_string()
    } else {
        format!("_{name}")
    }
}

/// The result of `+` or `-` on two doubles, rounded to a double as JS does.
fn rounded(code: String) -> Py {
    Py {
        is_num: true,
        is_double: true,
        ..Py::atom(format!("_js_num({code})"))
    }
}

fn truthy(value: Py) -> Py {
    if value.is_bool {
        value
    } else if value.is_str {
        // J87: a proven `str` is falsy exactly when empty, in both languages.
        Py::boolean(format!("{} != \"\"", value.at(CMP + 1)), CMP)
    } else {
        Py::boolean(format!("_js_truthy({})", value.code), ATOM)
    }
}

/// J87: look through parentheses only (a type assertion or `!` proves nothing).
fn strip_parens<'b, 'a>(e: &'b Expression<'a>) -> &'b Expression<'a> {
    match e {
        Expression::ParenthesizedExpression(p) => strip_parens(&p.expression),
        other => other,
    }
}

/// `exits` for `types::completes` (J87).
pub(crate) fn exits_pub(s: &Statement<'_>) -> bool {
    exits(s)
}

/// Look through parentheses and type-only wrappers.
fn strip<'b, 'a>(e: &'b Expression<'a>) -> &'b Expression<'a> {
    match e {
        Expression::ParenthesizedExpression(p) => strip(&p.expression),
        Expression::TSAsExpression(x) => strip(&x.expression),
        Expression::TSSatisfiesExpression(x) => strip(&x.expression),
        Expression::TSNonNullExpression(x) => strip(&x.expression),
        Expression::TSTypeAssertion(x) => strip(&x.expression),
        other => other,
    }
}

fn is_nullish_literal(e: &Expression<'_>) -> bool {
    match strip(e) {
        Expression::NullLiteral(_) => true,
        Expression::Identifier(id) => id.name == "undefined",
        _ => false,
    }
}

fn is_entries_call(e: &Expression<'_>) -> bool {
    matches!(strip(e), Expression::CallExpression(c)
        if c.arguments.is_empty()
            && matches!(strip(&c.callee), Expression::StaticMemberExpression(m) if m.property.name == "entries"))
}

fn is_array_index(key: &str) -> bool {
    !key.is_empty()
        && key.bytes().all(|b| b.is_ascii_digit())
        && (key == "0" || !key.starts_with('0'))
}

fn statement_kind(s: &Statement<'_>) -> &'static str {
    match s {
        Statement::ClassDeclaration(_) => "class",
        Statement::LabeledStatement(_) => "labelled statement",
        Statement::ThrowStatement(_) => "throw",
        Statement::TryStatement(_) => "try",
        Statement::SwitchStatement(_) => "switch",
        Statement::DoWhileStatement(_) => "do-while",
        Statement::ForStatement(_) => "C-style for loop",
        Statement::ForInStatement(_) => "for-in",
        Statement::WithStatement(_) => "with",
        Statement::DebuggerStatement(_) => "debugger",
        Statement::TSEnumDeclaration(_) => "enum",
        Statement::ExportDefaultDeclaration(_) => "export default",
        Statement::ExportAllDeclaration(_) => "export *",
        Statement::ExpressionStatement(_) => "top-level statement",
        Statement::IfStatement(_) | Statement::WhileStatement(_) | Statement::ForOfStatement(_) => {
            "top-level statement"
        }
        _ => "statement",
    }
}

/// Why a regex is refused: the text after `unsupported ` in the diagnostic.
const REGEX_SYNTAX: &str = "regex syntax";

/// Deepest group nesting accepted: Python's `re` parser recurses per group, so a deep enough
/// nesting is a `RecursionError` at import rather than a pattern.
const REGEX_MAX_DEPTH: usize = 64;

/// Largest `{n,m}` bound accepted: past `re`'s MAXREPEAT a bound is an error at import.
const REGEX_MAX_REPEAT: u32 = 65_535;

/// Stands for a `${...}` substitution while a `new RegExp(`...`)` template is translated (J86): a
/// private-use plane-15 character, accepted only as the whole body of a `{n}` repeat count.
const REGEX_HOLE: char = '\u{F0000}';

fn regex_hole_misplaced() -> String {
    "RegExp substitution anywhere but a whole {n} repeat count".to_string()
}

/// The code unit of a `\xHH` (2 digits) or `\uHHHH` (4 digits) escape starting at `chars[at]`
/// (the `x` or `u`), or None when the digits are not there (Annex B would read it as a literal
/// letter, which is refused rather than relied on).
fn hex_escape(chars: &[char], at: usize) -> Option<u16> {
    let width = if chars.get(at) == Some(&'x') { 2 } else { 4 };
    let digits: String = chars.get(at + 1..at + 1 + width)?.iter().collect();
    if digits.len() != width || !digits.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    u16::from_str_radix(&digits, 16).ok()
}

/// One member of a character class, as written in the translation.
struct ClassAtom {
    text: String,
    /// The single UTF-16 code unit it matches, or None for a class escape (`\d`, `\w`).
    unit: Option<u16>,
    /// An unescaped `-`, which may join two members into a range.
    dash: bool,
}

/// A JS regex (no flags) as a Python `re` pattern compiled with `re.ASCII`, or the reason it is
/// refused. The pattern is parsed against a whitelist grammar, not passed through: every pattern
/// this returns is valid in JS without flags, means the same in both engines, and compiles under
/// `re` (J85-R2 L3). Anything else (syntax whose meaning differs, Annex B leniencies such as a
/// bare `{` or a quantified lookahead, and patterns JS itself rejects) is refused here, at
/// compile time, rather than surfacing as `re.error` when the module is imported.
pub fn translate_regex(pattern: &str) -> Result<String, String> {
    let chars: Vec<char> = pattern.chars().collect();
    let syntax = || REGEX_SYNTAX.to_string();
    let mut out = String::new();
    // Open groups: whether each is a lookaround (which takes no quantifier once closed).
    let mut groups: Vec<bool> = Vec::new();
    // J86: inside a lookbehind only single-width atoms are accepted, so its width is fixed (what
    // Python's `re` requires) and matching it backwards (JS) or forwards (Python) is the same.
    let mut in_lookbehind = false;
    // The previous term is an atom a quantifier may follow, and it has not been quantified yet.
    let mut quantifiable = false;
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        match c {
            '\\' => {
                let next = *chars.get(i + 1).ok_or_else(syntax)?;
                i += 1;
                quantifiable = true;
                match next {
                    'd' => out.push_str("[0-9]"),
                    'w' => out.push_str("[A-Za-z0-9_]"),
                    'D' => out.push_str("[^0-9]"),
                    'W' => out.push_str("[^A-Za-z0-9_]"),
                    'b' => {
                        out.push_str("\\b");
                        quantifiable = false;
                    }
                    // Python's `\B` never matches in an empty string; JS's does (`/\B/.test('')`).
                    'B' => {
                        return Err(
                            "regex \\B, which Python's re does not match in an empty string"
                                .to_string(),
                        );
                    }
                    'n' | 'r' | 't' => {
                        out.push('\\');
                        out.push(next);
                    }
                    // J86: `\xHH` and `\uHHHH`, one UTF-16 code unit each (no `u` flag).
                    'x' | 'u' => {
                        let unit = hex_escape(&chars, i).ok_or_else(syntax)?;
                        out.push_str(&format!("\\u{unit:04x}"));
                        i += if next == 'x' { 2 } else { 4 };
                    }
                    '/' => out.push('/'),
                    c if "^$\\.*+?()[]{}|-".contains(c) => {
                        out.push('\\');
                        out.push(c);
                    }
                    _ => return Err(syntax()),
                }
            }
            '[' => {
                i = regex_class(&chars, i, &mut out)?;
                quantifiable = true;
            }
            '(' => {
                if in_lookbehind {
                    return Err("regex group inside a lookbehind".to_string());
                }
                out.push('(');
                let lookahead = if chars.get(i + 1) == Some(&'?') {
                    let kind = *chars.get(i + 2).ok_or_else(syntax)?;
                    if kind == '<' && matches!(chars.get(i + 3), Some('=' | '!')) {
                        // J86: a lookbehind (not a named group, which stays refused).
                        out.push('?');
                        out.push('<');
                        out.push(chars[i + 3]);
                        i += 3;
                        in_lookbehind = true;
                        groups.push(true);
                        if groups.len() > REGEX_MAX_DEPTH {
                            return Err(format!(
                                "regex nesting deeper than {REGEX_MAX_DEPTH} groups"
                            ));
                        }
                        quantifiable = false;
                        i += 1;
                        continue;
                    }
                    if !matches!(kind, ':' | '=' | '!') {
                        return Err(syntax());
                    }
                    out.push('?');
                    out.push(kind);
                    i += 2;
                    kind != ':'
                } else {
                    false
                };
                groups.push(lookahead);
                if groups.len() > REGEX_MAX_DEPTH {
                    return Err(format!(
                        "regex nesting deeper than {REGEX_MAX_DEPTH} groups"
                    ));
                }
                quantifiable = false;
            }
            ')' => {
                let lookahead = groups.pop().ok_or_else(|| {
                    "regex `)` without a matching `(`, a SyntaxError in JS".to_string()
                })?;
                in_lookbehind = false;
                out.push(')');
                quantifiable = !lookahead;
            }
            '|' | '^' | '$' if in_lookbehind => {
                return Err(format!("regex `{c}` inside a lookbehind"));
            }
            '|' => {
                out.push('|');
                quantifiable = false;
            }
            '^' => {
                out.push('^');
                quantifiable = false;
            }
            '$' => {
                out.push_str("\\Z");
                quantifiable = false;
            }
            '.' => {
                out.push_str("[^\\n\\r\\u2028\\u2029]");
                quantifiable = true;
            }
            '*' | '+' | '?' | '{' if in_lookbehind => {
                return Err(format!("regex quantifier `{c}` inside a lookbehind"));
            }
            '*' | '+' | '?' | '{' => {
                if !quantifiable {
                    return Err(format!("regex quantifier `{c}` with nothing to repeat"));
                }
                if c == '{' {
                    let close = (i..chars.len())
                        .find(|&j| chars[j] == '}')
                        .ok_or_else(syntax)?;
                    let body: String = chars[i + 1..close].iter().collect();
                    if body == REGEX_HOLE.to_string() {
                        // J86: `{${n}}`, the count supplied at run time.
                        out.push('{');
                        out.push(REGEX_HOLE);
                        out.push('}');
                        i = close + 1;
                        if chars.get(i) == Some(&'?') {
                            out.push('?');
                            i += 1;
                        }
                        quantifiable = false;
                        continue;
                    }
                    let (min, max) = match body.split_once(',') {
                        None => (body.as_str(), Some(body.as_str())),
                        Some((min, "")) => (min, None),
                        Some((min, max)) => (min, Some(max)),
                    };
                    let bound = |text: &str| -> Result<u32, String> {
                        if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
                            return Err(syntax());
                        }
                        match text.parse::<u32>() {
                            Ok(n) if n <= REGEX_MAX_REPEAT => Ok(n),
                            _ => Err(format!("regex repeat count above {REGEX_MAX_REPEAT}")),
                        }
                    };
                    let min = bound(min)?;
                    let max = max.map(bound).transpose()?;
                    if max.is_some_and(|max| min > max) {
                        return Err(format!(
                            "regex repeat {{{body}}} with min above max, a SyntaxError in JS"
                        ));
                    }
                    out.push('{');
                    out.push_str(&body);
                    out.push('}');
                    i = close;
                } else {
                    out.push(c);
                }
                if chars.get(i + 1) == Some(&'?') {
                    out.push('?');
                    i += 1;
                }
                quantifiable = false;
            }
            ']' | '}' => return Err(syntax()),
            REGEX_HOLE => return Err(regex_hole_misplaced()),
            // Without the `u` flag JS reads the pattern as UTF-16 code units, so an astral
            // literal is two units (in a class, two members). The subject is split the same
            // way at match time (`_js_code_units`), so `.` and `[^x]` match one unit, as in JS.
            c if c as u32 >= 0x10000 => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
                quantifiable = true;
            }
            _ => {
                out.push(c);
                quantifiable = true;
            }
        }
        i += 1;
    }
    if !groups.is_empty() {
        return Err("regex `(` without a matching `)`, a SyntaxError in JS".to_string());
    }
    Ok(out)
}

/// The class opening at `chars[open]`, written to `out`; returns the index of its closing `]`.
fn regex_class(chars: &[char], open: usize, out: &mut String) -> Result<usize, String> {
    let syntax = || REGEX_SYNTAX.to_string();
    let mut i = open + 1;
    out.push('[');
    if chars.get(i) == Some(&'^') {
        out.push('^');
        i += 1;
    }
    // `[]` and `[^]` mean "nothing" and "anything" in JS and are errors in `re`.
    if chars.get(i) == Some(&']') {
        return Err(syntax());
    }
    let mut atoms: Vec<ClassAtom> = Vec::new();
    loop {
        let c = *chars.get(i).ok_or_else(syntax)?;
        match c {
            ']' => break,
            // Doubled, these are set operations under the `v` flag and warnings in `re`.
            '&' | '~' | '|' | '-' if chars.get(i + 1) == Some(&c) => return Err(syntax()),
            '\\' => {
                let next = *chars.get(i + 1).ok_or_else(syntax)?;
                i += 1;
                let (text, unit) = match next {
                    'd' => ("0-9".to_string(), None),
                    'w' => ("A-Za-z0-9_".to_string(), None),
                    'b' => ("\\b".to_string(), Some(0x08)),
                    'n' => ("\\n".to_string(), Some(0x0a)),
                    'r' => ("\\r".to_string(), Some(0x0d)),
                    't' => ("\\t".to_string(), Some(0x09)),
                    // J86: `\xHH` and `\uHHHH`, one code unit each.
                    'x' | 'u' => {
                        let unit = hex_escape(chars, i).ok_or_else(syntax)?;
                        i += if next == 'x' { 2 } else { 4 };
                        (format!("\\u{unit:04x}"), Some(unit))
                    }
                    '/' => ("/".to_string(), Some(u16::from(b'/'))),
                    c if "^$\\.*+?()[]{}|-".contains(c) => (format!("\\{c}"), Some(c as u16)),
                    _ => return Err(syntax()),
                };
                atoms.push(ClassAtom {
                    text,
                    unit,
                    dash: false,
                });
            }
            '[' => atoms.push(ClassAtom {
                text: "\\[".to_string(),
                unit: Some(u16::from(b'[')),
                dash: false,
            }),
            REGEX_HOLE => return Err(regex_hole_misplaced()),
            c => {
                let mut units = [0u16; 2];
                let encoded = c.encode_utf16(&mut units);
                let astral = encoded.len() == 2;
                for &unit in encoded.iter() {
                    atoms.push(ClassAtom {
                        text: if astral {
                            format!("\\u{unit:04x}")
                        } else {
                            c.to_string()
                        },
                        unit: Some(unit),
                        dash: c == '-',
                    });
                }
            }
        }
        i += 1;
    }
    let mut k = 0;
    while k < atoms.len() {
        let is_range = k + 2 < atoms.len() && atoms[k + 1].dash && !atoms[k].dash;
        if !is_range {
            out.push_str(&atoms[k].text);
            k += 1;
            continue;
        }
        let (Some(lo), Some(hi)) = (atoms[k].unit, atoms[k + 2].unit) else {
            // `[a-\d]` is three members in JS (Annex B) and an error in `re`.
            return Err("regex class escape as a range endpoint".to_string());
        };
        if lo > hi {
            return Err(format!(
                "regex range out of order in UTF-16 code units (\\u{lo:04x}-\\u{hi:04x}), a SyntaxError in JS"
            ));
        }
        out.push_str(&atoms[k].text);
        out.push('-');
        out.push_str(&atoms[k + 2].text);
        k += 3;
        // A `-` straight after a range, not last: JS and `re` read `[a-c-e]` alike, but only by
        // grammar details this translator does not lean on.
        if k + 1 < atoms.len() && atoms[k].dash {
            return Err(syntax());
        }
    }
    out.push(']');
    Ok(i)
}

#[cfg(test)]
mod tests {
    use super::translate_regex;

    #[test]
    fn regex_translation() {
        assert_eq!(translate_regex("^[A-Za-z]:").unwrap(), "^[A-Za-z]:");
        assert_eq!(translate_regex("a$").unwrap(), "a\\Z");
        assert_eq!(translate_regex("\\d+").unwrap(), "[0-9]+");
        assert!(translate_regex("\\s").is_err());
        assert!(translate_regex("(?<n>a)").is_err());
        // J85-R F3: an astral literal is its two UTF-16 code units, in and out of a class.
        assert_eq!(
            translate_regex("^a.b$").unwrap(),
            "^a[^\\n\\r\\u2028\\u2029]b\\Z"
        );
        assert_eq!(translate_regex("\u{1F600}").unwrap(), "\\ud83d\\ude00");
        assert_eq!(translate_regex("[\u{1F600}]").unwrap(), "[\\ud83d\\ude00]");
    }
}
