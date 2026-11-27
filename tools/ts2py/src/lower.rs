//! TypeScript AST (oxc) to Python source, for the subset `SUBSET.md` lists.
//!
//! Every construct outside the subset is refused with a span and a construct name; lowering keeps
//! going after a refusal so one run reports every offence, and the caller writes nothing when any
//! refusal was recorded.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use oxc_ast::ast::*;
use oxc_span::{GetSpan, Span};

use crate::adapters::{AdapterKind, AdapterTable, Contract};
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
const MUL: u8 = 12;
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
    /// J89-3: always a Python `float` (`types::Fact::f64`); set only with `is_num` and `is_double`.
    is_f64: bool,
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
    /// J91-1 (#341): always a `_JsMap` itself (`types::Fact::map`).
    is_map: bool,
    /// J91-1: always a safe int (`types::Fact::int_`); set only with `is_num` and `is_double`.
    is_int: bool,
    /// J91-1: always an index (`types::Fact::idx`); set only with `is_int`.
    is_idx: bool,
    /// J87: always a compiled `re.Pattern` without the `g` flag.
    is_regex: bool,
    /// J91-3 (#341): always a `_JsGlobalRegExp` (`types::Fact::gregex`).
    is_gregex: bool,
    /// J91-3: a list, Map or Set nothing else can reach (`types::Fact::own`).
    own: bool,
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
            f64: self.is_f64 && self.is_num && self.is_double,
            bool_: self.is_bool,
            list: self.is_list,
            map: self.is_map,
            int_: self.is_int && self.is_num && self.is_double,
            idx: self.is_idx && self.is_int && self.is_num && self.is_double,
            regex: self.is_regex,
            gregex: self.is_gregex,
            match_: self.is_match,
            tuple: self.tuple.clone(),
            elem: self.elem.clone(),
            own: self.own,
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
                self.is_f64 = true;
                self.is_double = true;
                self.is_bool = true;
                self.is_list = true;
                self.is_map = true;
                self.is_int = true;
                self.is_idx = true;
                self.is_regex = true;
                self.is_gregex = true;
                self.own = true;
            }
            Some(f) => {
                self.is_str |= f.str_;
                if f.num {
                    self.is_num = true;
                    self.is_double = true;
                }
                if f.f64 {
                    self.is_num = true;
                    self.is_double = true;
                    self.is_f64 = true;
                }
                self.is_bool |= f.bool_;
                self.is_list |= f.list;
                self.is_map |= f.map;
                if f.int_ {
                    self.is_num = true;
                    self.is_double = true;
                    self.is_int = true;
                }
                if f.idx {
                    self.is_num = true;
                    self.is_double = true;
                    self.is_int = true;
                    self.is_idx = true;
                }
                self.is_regex |= f.regex;
                self.is_gregex |= f.gregex;
                self.own |= f.own;
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
            is_f64: both.f64,
            is_str: both.str_,
            is_list: both.list,
            is_map: both.map,
            is_int: both.int_,
            is_idx: both.idx,
            is_regex: both.regex,
            is_gregex: both.gregex,
            own: both.own,
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

/// J91-3 (#341): what `x.push(...)`, `x.set(k, v)` or `x.add(v)` (`args` lowered) proves `x` holds
/// once it ran: `x` is what the method needs (a list, a Map), still `own` as far as this use goes,
/// holding the shallow facts of what was put in (a spread puts in anything). A Map's key drops `f64`
/// (`-0` is stored as `0`) and a Set keeps only `str` (a `str` item is itself; a number's tag may
/// not be). None: any other method.
fn fill_fact(method: &str, args: &[Py], spread: bool) -> Option<Fact> {
    // An optimistic argument (`Py::top`) puts in "anything" for now: its `fact()` is `Fact::top`,
    // the identity of the meet, as every optimistic value is until a later round knows it.
    match method {
        "push" => {
            let elem = if spread || args.is_empty() {
                None
            } else {
                let mut facts = args.iter().map(|a| a.fact().shallow());
                let first = facts.next()?;
                Some(Box::new(facts.fold(first, |acc, f| acc.meet(&f))))
            };
            Some(Fact {
                list: true,
                own: true,
                elem,
                ..Fact::default()
            })
        }
        "set" => {
            let elem = match args {
                [k, v] if !spread => {
                    let key = if k.top {
                        Fact::top()
                    } else {
                        Fact {
                            f64: false,
                            ..k.fact().shallow()
                        }
                    };
                    Some(Box::new(Fact {
                        list: true,
                        tuple: Some(vec![key, v.fact().shallow()]),
                        ..Fact::default()
                    }))
                }
                _ => None,
            };
            Some(Fact {
                map: true,
                own: true,
                elem,
                ..Fact::default()
            })
        }
        "add" => {
            let elem = match args {
                [v] if !spread && v.top => Some(Box::new(Fact::top())),
                [v] if !spread && v.is_str => Some(Box::new(Fact::str_())),
                _ => None,
            };
            Some(Fact {
                own: true,
                elem,
                ..Fact::default()
            })
        }
        _ => None,
    }
}

/// J91-3 (#341): what a sealed binding of the `own` value `fact` keeps: its flags, `own`, and what
/// it holds, each element shallow (an element is a value other reads can reach and change; a Map's
/// entry is a fresh `[key, value]` pair per iteration, so the pair's length stays, each side
/// shallow).
fn sealed_fact(fact: &Fact) -> Fact {
    let elem = fact.elem.as_deref().map(|e| {
        Box::new(match (&e.tuple, fact.map) {
            (Some(pair), true) if pair.len() == 2 && !e.top => Fact {
                tuple: Some(pair.iter().map(Fact::shallow).collect()),
                ..e.shallow()
            },
            _ => e.shallow(),
        })
    });
    Fact {
        own: true,
        elem,
        ..fact.shallow()
    }
}

/// J91-3 (#341): what a builtin method's answer is, read from what its receiver or argument holds:
/// `m.get(k)` of a Map whose entries are proven `[K, V]` pairs is a `V` or `undefined`; `s.match(re)`
/// of a `g` regex is `null` or a fresh list of `str`s (`_js_m_match`: every match's text through
/// `_js_from_units`, a `str`, or `None` when there is none). None: nothing beyond the method's `Ret`.
fn contents_fact(method: &str, receiver: &Py, args: &[Fact]) -> Option<Fact> {
    match method {
        "get" if receiver.is_map && !receiver.top && args.len() == 1 => {
            let entry = receiver.elem.as_deref()?;
            if entry.top {
                // No entry was ever set: `get` answers `undefined`.
                return Some(Fact {
                    is_undef: true,
                    ..Fact::default()
                });
            }
            let value = entry.tuple.as_ref().filter(|t| t.len() == 2)?[1].shallow();
            Some(value.meet(&Fact {
                is_undef: true,
                ..Fact::default()
            }))
        }
        "match" if args.len() == 1 && args[0].gregex && !args[0].top => Some(Fact {
            nn: Some(Box::new(Fact {
                list: true,
                own: true,
                elem: Some(Box::new(Fact::str_())),
                ..Fact::default()
            })),
            no_undef: true,
            ..Fact::default()
        }),
        _ => None,
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
    // J88-2 (#316 G2: eventlog, tokenledger, storage/logsegment).
    ("endsWith", 1, 1, None, Ret::Bool),
    ("trim", 0, 0, None, Ret::Str),
    ("values", 0, 0, None, Ret::List),
    ("subarray", 0, 2, None, Ret::Any),
    // J89-2 (#316 G3: memory/usage, memory/retrieval).
    ("toFixed", 0, 1, None, Ret::Str),
    ("match", 1, 1, None, Ret::Any),
    ("charCodeAt", 0, 1, None, Ret::Num),
    // J89-4a (#316 G3 U2: memory/store).
    ("forEach", 1, 1, Some(0), Ret::Any),
    ("keys", 0, 0, None, Ret::List),
    ("copyWithin", 2, 3, None, Ret::List),
    // J90-2 (#316 G4: storage/hotindex).
    ("delete", 1, 1, None, Ret::Bool),
    // J90-3 (#316 G4: storage/retention): `Buffer.prototype.equals`.
    ("equals", 1, 1, None, Ret::Bool),
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
    // J90-3: Buffer.prototype's `equals` (a Uint8Array method the subset now calls).
    "equals",
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
    // J88-2 (#316 G2). `JSON.stringify` with a replacer or a space goes to its own helper.
    ("Date", "now", "_js_now", 0, 0, Ret::Num),
    (
        "Object",
        "assign",
        "_js_object_assign",
        1,
        usize::MAX,
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
    /// J89-4a: the module's generator functions (`function*`), by source name.
    pub generators: HashSet<String>,
    /// J89-5: the data fields each named object type declares (`types::TypeDecls::fields`), so a
    /// module that imports the type (`import { type Pool }`) reads `pool.facts` as the data field
    /// the declaring module reads it as.
    pub type_fields: BTreeMap<String, BTreeSet<String>>,
    /// J91-3 (#341): per exported function, what a call of it from another module proves of its
    /// answer: what every return of the body that call runs proved (`Lowerer::export_rets`), from
    /// the previous round of the whole compile (`lib.rs`). Empty in the first round.
    pub rets: HashMap<String, Fact>,
}

/// Everything about the other modules of a multi-module compile a module needs (J86).
#[derive(Clone, Default)]
pub struct ModuleCtx {
    /// This module's path, as printed (`src/memory/factfile.ts`).
    pub path: String,
    /// Every compiled module, by its normalised `.ts` path.
    pub modules: HashMap<String, ModuleExports>,
    /// Method names declared by any class in any compiled module, and by the adapter classes.
    pub class_methods: HashSet<String>,
    /// Where the hand-written adapters are imported from (`._ts2py_adapters`).
    pub adapter_module: String,
    /// #337: the host's adapter rows (`host.rs`).
    pub adapters: std::sync::Arc<AdapterTable>,
    /// J90-2: the compiled modules this one imports that import it back, directly or not (an
    /// import cycle, as `hotindex.ts` and `memory/store.ts` are). Their names are imported at
    /// the END of the Python module (`late_imports`), when every name of this one is bound.
    pub cyclic_imports: HashSet<String>,
}

/// A class being lowered: its members as JS spells them.
#[derive(Clone, Default)]
struct ClassCtx {
    /// Fields, methods and getters this class (or a compiled base) declares.
    members: HashSet<String>,
    /// Methods only (callable as `this.m(...)`).
    methods: HashSet<String>,
}

/// J91-3 (#341): how a local is read where the read lets nothing else reach its value
/// (RULES.md, *J91-3 rules*). Any other read of a `const` local unseals it (`Assume::unsealed`).
#[derive(Clone, Copy, PartialEq)]
enum Seal {
    /// The receiver of `push` / `set` / `get` / `has` / `add`, the object of `.length` / `.size`,
    /// or a for-of's iterable: the value is read or changed in place, in a way the compiler sees.
    Use,
    /// `return x` in the body that declares `x`: the caller gets the only reference, provided no
    /// nested function that reads `x` can run after the return (`returnable`).
    Return,
    /// `f(...)`, `f` a `const` arrow, called from the body that declares it.
    Call,
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
    /// J90-P2 (#337): source names of adapter functions whose row promises
    /// `Contract::CompareCodepoints`.
    codepoint_fns: HashSet<String>,
    /// J90-P6 (#337): source names bound to Node's `createHash` (`node:crypto`).
    hash_fns: HashSet<String>,
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
    /// J90-2: the same, from a module of an import cycle (`ModuleCtx::cyclic_imports`): written
    /// after the body, so the cycle imports whichever module comes first without a name unbound.
    pub late_imports: BTreeMap<String, BTreeSet<String>>,
    /// J90-2: the Python names `late_imports` binds; none may be read while the module itself is
    /// being executed (a module-level initializer, an `extends`), when it may not be bound yet.
    cyclic_py: HashSet<String>,
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
    /// J90-P: module-level `const` arrows `(v) => Object.entries(v)`, which `new Map(f(x))`
    /// reads as `new Map(Object.entries(x))`.
    entries_aliases: HashSet<String>,
    /// J89-2: module-level `let` bindings (Python module globals a function may assign).
    module_lets: HashSet<String>,
    /// J89-2: per function being lowered, the module `let`s it assigns (`global` declarations).
    global_writes: Vec<BTreeSet<String>>,
    /// J87: non-exported module `const`s bound to an array literal: frozen unless a use escapes.
    frozen: HashSet<String>,
    /// J87: the module's interfaces and type aliases.
    types: TypeDecls,
    /// J87: the data fields a binding's annotation declares, by (scope owner, source name).
    declared: HashMap<(u32, String), BTreeSet<String>>,
    /// J87: the call being lowered is a whole expression statement.
    statement_call: bool,
    /// J89-4a: a spread argument must be an array PROVEN a list (`a.splice(i, n, ...xs)`).
    spread_list: bool,
    /// J89-4a: lowering the body of a `function*` (a module generator function): a `yield`
    /// statement is allowed and a `return` takes no value.
    in_generator: bool,
    /// J89-4a: the `yield` statements lowered in the current generator body.
    yields: usize,
    /// J89-4a: how many `try` statements enclose the statement being lowered.
    try_depth: usize,
    /// J89-4a: the methods of the `ImportedClass` adapters this module imports.
    imported_methods: HashSet<String>,
    /// J89-4a: the generator functions this module declares or imports, by source name.
    generator_fns: HashSet<String>,
    /// J89-4a: the call being lowered is a for-of's iterable or an array spread's argument, the
    /// two places a generator function may be called.
    generator_call_ok: bool,
    /// J87: frozen module constants bound to an object literal (read by member only).
    frozen_objects: HashSet<String>,
    /// J87: `const` bindings (never reassigned), which a guard may narrow.
    consts: HashSet<Key>,
    /// J87: narrowed facts in force, innermost last: (binding, what it is here).
    narrow: Vec<(Key, Fact)>,
    /// J87: the identifier being lowered is read where its value cannot escape (`peek`).
    peek_read: bool,
    /// J91-3 (#341): the identifier lowered next is read in a sealed use of this kind (`seal`).
    seal: Option<Seal>,
    /// J91-3 (#341): imported functions of the other compiled modules, with what a call proves.
    imported_rets: HashMap<String, Fact>,
    /// J91-3 (#341): adapter functions whose row promises a `str` (`Contract::Str`).
    str_fns: HashSet<String>,
    /// J88-2: `import * as fs from 'node:fs'`: local name -> the module specifier.
    namespaces: HashMap<String, String>,
    /// J88-2: lines to emit before the statement being lowered (an arrow function used as a value
    /// becomes a nested `def` there), and that statement's indent.
    pre: Vec<String>,
    cur_indent: usize,
    /// J88-2: how many callback lambdas enclose the expression being lowered.
    in_callback: usize,
    /// J90-P2: the operand of `&&` being lowered cannot change an array's length (`pure_test`),
    /// so `x.length === N` on the left may narrow `x` to an array of exactly N elements there.
    length_ok: bool,
    /// J89-3: `const` bindings of a `new Float64Array(n)` (SUBSET.md, *Typed arrays*).
    typed_arrays: HashSet<Key>,
    /// J89-3: `const` bindings of an array literal: a fresh array no parameter can alias.
    fresh_arrays: HashSet<Key>,
    /// J89-3: the proven copy of a counted loop being lowered (`fast_loop`).
    fast: Option<FastLoop>,
    /// J89-3: `fast_loop` emitted the loop's init already; `c_for_loop` skips it once.
    fast_init_done: bool,
    /// J89-3: an assignment in the proven copy gave a carried `let` a value not proven a number.
    fast_carry_failed: bool,
    /// J90-P3: the proven copies enclosing `fast` (a counted loop nested in another's copy),
    /// innermost last: a binding the outer copy declares keeps its key inside the inner one.
    fast_outer: Vec<FastLoop>,
    /// J90-P3: module `const`s bound to a positive integer literal (a counted loop's stride).
    int_consts: HashMap<String, u64>,

    /// J90-P3: lowering the general loop of a proven copy (the path a failed guard takes): a
    /// counted loop nested in it is lowered once, without a copy of its own.
    in_fallback: usize,

    /// J90-P6: lowering a comprehension's iterable, where an assignment expression is a
    /// SyntaxError: a guarded inline expansion there binds no temporary (`hot`).
    no_walrus: usize,
    /// J90-P6: lowering an inline callback's body (a comprehension element): no expansion.
    hot_comp: usize,
    /// J90-P6: the temporaries `hot` has bound, for unique names.
    hot_tmp: usize,
    /// J91-1 (#341): per Python name, what the last read of it proved, stamped with `fact_seq`
    /// when it was read. A guarded expansion takes an operand's fact only from a read made while
    /// lowering that very expression (`proven`): every operand it would test is a name read there.
    name_facts: HashMap<String, (Fact, u64)>,
    fact_seq: u64,
}

/// J89-3: what `fast_loop_plan` found in a counted loop's body.
#[derive(Default)]
struct LoopScan {
    var: String,
    assigned: HashSet<String>,
    declared: HashSet<String>,
    typed: HashSet<String>,
    plain: HashSet<String>,
    numeric: BTreeSet<String>,
    pushed: HashSet<String>,
    filled: HashSet<String>,
    /// J90-P: plain arrays whose `.length` the body reads (source names).
    measured: HashSet<String>,
    /// J90-P3: the variables of counted loops nested in the body.
    loop_vars: HashSet<String>,
    /// J90-P3: per plain array read at `i + c`, the largest `c` (0 for `x[i]`).
    offsets: HashMap<String, u64>,
    /// J90-P3: plain arrays some read of which is an operand of arithmetic or a comparison
    /// (directly, or through a `const` the body declares from it): their elements are checked
    /// numbers. The others are only bounds-checked and read as they are.
    numeric_arrays: HashSet<String>,
    /// J90-P3: a `const` the body declares from `x[i + c]`, by name: the array `x`.
    from_read: HashMap<String, String>,
    /// J90-P3: the expression `scan_expr` is about to walk is a SINK, where a value is only
    /// stored or tested and no code can run on it: an array literal's element, `push`'s argument,
    /// an `if` test, a `const` initializer. Anywhere else, reading an element (or a `const` read
    /// from one) makes its array `numeric_arrays`.
    sink: bool,
}

/// J89-3: a counted loop `fast_loop` versions: the bound's Python code, and the guard's parts.
struct LoopPlan {
    var: String,
    bound: String,
    bound_name: Option<String>,
    typed: BTreeSet<String>,
    plain: BTreeSet<String>,
    filled: BTreeSet<String>,
    /// J90-P: plain arrays whose `.length` the body reads, checked lists before the loop.
    measured: BTreeSet<String>,
    /// J90-P3: the stride (`i += S`), 1 for `i += 1` / `i++`.
    step: u64,
    /// J90-P3: per plain array, the largest offset `c` of a read `x[i + c]`.
    offsets: BTreeMap<String, u64>,
    /// J90-P3: plain arrays read only as values (never an operand): bounds-checked, not
    /// `_js_doubles`-checked, and each read proves nothing about its element.
    pass: BTreeSet<String>,
    speculated: Vec<String>,
    carried: Vec<String>,
    declared: HashSet<String>,
}

/// J89-3: what the proven copy of a counted loop `for (let i = a; i < b; i += 1)` may assume: `i`
/// is an int with `0 <= i < b`, `b` is at most the length of every array the body indexes by `i`,
/// each plain array so indexed holds only proven numbers in that range, and nothing in the body
/// can change any of it (`Lowerer::fast_loop_plan`).
#[derive(Clone)]
struct FastLoop {
    /// The loop's span start (the `ver` of the keys the copy declares).
    span: u32,
    /// Names the body declares.
    declared: HashSet<String>,
    /// The loop variable (source name).
    var: String,
    /// Float64Arrays the body indexes by `i` (source names).
    typed: HashSet<String>,
    /// Plain arrays the body reads by `i`, checked by `_js_doubles` (source names).
    plain: HashSet<String>,
    /// J90-P3: plain arrays the body reads by `i` (or `i + c`) as values only, bounds-checked.
    pass: HashSet<String>,
    /// Fresh local arrays (`fresh_arrays`) the body writes at `i`, checked a list long enough.
    filled: HashSet<String>,
    /// Outer `let`s the body assigns and uses as operands, checked a number before the loop and
    /// proven one throughout it when every assignment in the copy assigns a proven number.
    carried: HashSet<String>,
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
            codepoint_fns: HashSet::new(),
            hash_fns: HashSet::new(),
            catch_params: Vec::new(),
            exports: Vec::new(),
            scopes: Vec::new(),
            owners: HashMap::new(),
            tmp: 0,
            ctx,
            classes: HashMap::new(),
            imports: BTreeMap::new(),
            late_imports: BTreeMap::new(),
            cyclic_py: HashSet::new(),
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
            entries_aliases: HashSet::new(),
            module_lets: HashSet::new(),
            global_writes: Vec::new(),
            frozen: HashSet::new(),
            types: TypeDecls::default(),
            declared: HashMap::new(),
            statement_call: false,
            spread_list: false,
            in_generator: false,
            yields: 0,
            try_depth: 0,
            imported_methods: HashSet::new(),
            generator_fns: HashSet::new(),
            generator_call_ok: false,
            frozen_objects: HashSet::new(),
            consts: HashSet::new(),
            narrow: Vec::new(),
            peek_read: false,
            seal: None,
            imported_rets: HashMap::new(),
            str_fns: HashSet::new(),
            namespaces: HashMap::new(),
            pre: Vec::new(),
            cur_indent: 0,
            in_callback: 0,
            length_ok: false,
            typed_arrays: HashSet::new(),
            fresh_arrays: HashSet::new(),
            fast: None,
            fast_init_done: false,
            fast_carry_failed: false,
            fast_outer: Vec::new(),
            int_consts: HashMap::new(),
            in_fallback: 0,
            no_walrus: 0,
            hot_comp: 0,
            hot_tmp: 0,
            name_facts: HashMap::new(),
            fact_seq: 0,
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

    /// J91-3 (#341): what a call from another module of each exported function proves of its
    /// answer, under the settled assumptions: a call by the exported name runs the guarded entry
    /// (an exported typed function is always wrapped), so what both bodies' returns proved, met;
    /// an untyped function's one body. A function whose returns no round saw proves nothing here
    /// (`Observed::next` keeps such a return optimistic; across modules it is not taken), nor does
    /// any name in `rebound` (hand-written Python rebinds it, so the call may not run this body).
    pub fn export_rets(&self, rebound: &[&str]) -> HashMap<String, Fact> {
        let mut out = HashMap::new();
        for (name, sig) in &self.sigs {
            if !sig.exported
                || rebound.contains(&name.as_str())
                || self.generator_fns.contains(name)
            {
                continue;
            }
            let get = |typed: bool| {
                self.assume.facts.get(&Key::Ret {
                    name: name.clone(),
                    typed,
                })
            };
            let fact = if sig.typed() {
                match (get(true), get(false)) {
                    (Some(a), Some(b)) => a.meet(b),
                    _ => continue,
                }
            } else {
                match get(false) {
                    Some(f) => f.clone(),
                    None => continue,
                }
            };
            if !fact.top && !fact.is_unknown() {
                out.insert(name.clone(), fact);
            }
        }
        out
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
            // J89-3: a binding the proven copy of a counted loop declares is its own key there.
            // J90-P3: or the enclosing copy that declares it, when copies nest.
            let ver = if i + 1 == self.scopes.len() {
                self.fast
                    .iter()
                    .chain(self.fast_outer.iter().rev())
                    .find(|fast| fast.declared.contains(name))
                    .map_or(0, |fast| fast.span)
            } else {
                0
            };
            return Some(Key::Var {
                typed: self.typed,
                owner: self.scope_owner[i],
                name: name.to_string(),
                ver,
            });
        }
        if self.module_consts.contains(name) {
            return Some(Key::Var {
                typed: false,
                owner: MODULE,
                name: name.to_string(),
                ver: 0,
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
        let read = match self.var_key(name) {
            Some(key) => {
                let fact = self.lookup(&key);
                if let Some((_, narrowed)) = self.narrow.iter().rev().find(|(k, _)| *k == key) {
                    let narrowed = narrowed.clone();
                    py.with_fact(Some(&narrowed))
                } else {
                    py.with_fact(fact.as_ref())
                }
            }
            None => py,
        };
        // J91-1: what this read proves, for a guarded expansion of the expression it is in.
        self.fact_seq += 1;
        self.name_facts
            .insert(read.code.clone(), (read.fact(), self.fact_seq));
        read
    }

    /// J91-1 (#341): what is proven of the operand `code` of a guarded expansion: the fact of a
    /// read of that name made after `since` (while lowering the expression the expansion
    /// rewrites), never an optimistic one. Anything else proves nothing.
    fn proven(&self, code: &str, since: u64) -> Fact {
        match self.name_facts.get(code) {
            Some((fact, seq)) if *seq > since && !fact.top && is_name(code) => fact.clone(),
            _ => Fact::default(),
        }
    }

    /// J87: a `const` binding (local or module) named by `e`, which a guard may narrow.
    fn narrowable(&self, e: &Expression<'_>) -> Option<Key> {
        let Expression::Identifier(id) = strip_parens(e) else {
            return None;
        };
        let key = self.var_key(id.name.as_str())?;
        let module = matches!(key, Key::Var { owner: MODULE, .. });
        // J91-3 (#341): and nothing assigns the binding anywhere. A `const` and a `let` of one
        // name in two blocks of a function are one Python binding (one key), so the `const`'s key
        // in `consts` let a guard narrow the `let` past an assignment to it (Node `undefined`,
        // Python a TypeError: tests/j93.rs, `narrowed`). Syntactic (`Assume::assign_spans`).
        let assigned = self
            .assume
            .assign_spans
            .get(&key)
            .is_some_and(|spans| !spans.is_empty());
        ((module || self.consts.contains(&key) || self.assume.stable.contains(&key)) && !assigned)
            .then_some(key)
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
                // Both hold (the right one tested where the left one holds).
                (LogicalOperator::And, true) | (LogicalOperator::Or, false) => {
                    // A length the left proves holds past the right only if the right cannot
                    // change it either (J90-P2, `length_ok`).
                    let length_ok = self.length_ok;
                    self.length_ok = length_ok && self.pure_test(&l.right);
                    let mut out = self.narrowings(&l.left, when);
                    self.length_ok = length_ok;
                    let depth = self.narrow.len();
                    self.narrow.extend(out.iter().cloned());
                    let right = self.narrowings(&l.right, when);
                    self.narrow.truncate(depth);
                    out.extend(right);
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
            // J90-P: `Array.isArray(x)` true: x is a list.
            Expression::CallExpression(c)
                if when
                    && !c.optional
                    && c.arguments.len() == 1
                    && matches!(strip(&c.callee), Expression::StaticMemberExpression(m)
                        if !m.optional && m.property.name == "isArray"
                            && matches!(strip(&m.object), Expression::Identifier(o) if o.name == "Array"))
                    && !self.is_local("Array") =>
            {
                match c.arguments[0]
                    .as_expression()
                    .and_then(|x| self.narrowable(x))
                {
                    Some(key) => vec![(key, Fact::list())],
                    None => Vec::new(),
                }
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
                // J90-P2: `x.length === N` true, `x` an array: exactly N elements, while nothing
                // can change its length (`length_ok`: the rest of an `&&` that `pure_test` holds).
                if strict && equal && self.length_ok {
                    for (side, other) in [(&b.left, &b.right), (&b.right, &b.left)] {
                        let (Expression::StaticMemberExpression(m), Expression::NumericLiteral(n)) =
                            (strip_parens(side), strip_parens(other))
                        else {
                            continue;
                        };
                        if m.optional
                            || m.property.name != "length"
                            || n.value.fract() != 0.0
                            || !(0.0..=16.0).contains(&n.value)
                        {
                            continue;
                        }
                        let Some(key) = self.narrowable(&m.object) else {
                            continue;
                        };
                        let Some(mut fact) = self.current(&key).filter(|f| f.list && !f.top) else {
                            continue;
                        };
                        fact.tuple = Some(vec![Fact::default(); n.value as usize]);
                        return vec![(key, fact)];
                    }
                }
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
                        // J89-4a: a generator has one body, untyped (a guarded entry would have
                        // to `yield from` its typed twin), and its call answers a generator.
                        if f.generator
                            && let Some(sig) = self.sigs.get_mut(id.name.as_str())
                        {
                            sig.params.iter_mut().for_each(|p| *p = None);
                            self.generator_fns.insert(id.name.to_string());
                        }
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
                                    if v.kind == VariableDeclarationKind::Const
                                        && is_entries_alias(a)
                                    {
                                        self.entries_aliases.insert(id.name.to_string());
                                    }
                                }
                                init => {
                                    if v.kind == VariableDeclarationKind::Let {
                                        self.module_lets.insert(id.name.to_string());
                                    }
                                    if v.kind == VariableDeclarationKind::Const {
                                        self.module_consts.insert(id.name.to_string());
                                        if let Some(Expression::NumericLiteral(n)) = init
                                            && n.value >= 1.0
                                            && n.value.fract() == 0.0
                                            && n.value <= 1024.0
                                        {
                                            self.int_consts
                                                .insert(id.name.to_string(), n.value as u64);
                                        }
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

    /// J90-2: refuse a module-level initializer whose Python reads a name imported in a cycle:
    /// it runs while the module is executed, and the cycle may not have bound that name yet.
    fn module_eval_use(&mut self, code: &str, span: Span) {
        let mut hit: Vec<&String> = self
            .cyclic_py
            .iter()
            .filter(|py| uses_ident(code, py))
            .collect();
        hit.sort();
        if let Some(py) = hit.first() {
            let construct = format!("module-level use of {py}, imported in an import cycle");
            self.refuse(span, construct);
        }
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
                    self.re_export(e);
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
                // J89-2: a module-level `let` is a Python module global. Every function reads it
                // at call time (as JS reads the live binding); a function that assigns it declares
                // it `global` (`local_target`). It holds no facts: anything may be assigned to it.
                if v.kind == VariableDeclarationKind::Let {
                    for d in &v.declarations {
                        let BindingPattern::BindingIdentifier(id) = &d.id else {
                            self.refuse(d.span, "destructuring declaration");
                            continue;
                        };
                        let name = self.globals[id.name.as_str()].clone();
                        let Some(init) = &d.init else {
                            self.refuse(d.span, "module-level let without initializer");
                            continue;
                        };
                        if matches!(init, Expression::ArrowFunctionExpression(_)) {
                            self.refuse(d.span, "module-level let bound to a function");
                            continue;
                        }
                        let value = self.expr(init);
                        self.module_eval_use(&value.code, d.span);
                        out.push(format!("{name} = {}", value.code));
                    }
                    return;
                }
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
                            self.module_eval_use(&value.code, d.span);
                            out.push(format!("{name} = {}", value.code));
                            // J87: a frozen array keeps what its elements are; any other const
                            // keeps the flags of its value (the binding never changes).
                            let source = id.name.as_str();
                            let frozen = self.frozen.contains(source)
                                && !self.assume.escaped.contains(source);
                            let fact = value.fact();
                            let fact = if frozen {
                                // J91-3: a module constant is never `own` (every call shares it).
                                Fact {
                                    tuple: None,
                                    own: false,
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
                                    ver: 0,
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
        let typed_at = out.len();
        self.function_body(&typed_name, source, &sig.params, None, ret(true), out);
        if wrapped {
            self.typed = false;
            let guard = (sig.typed_py.as_str(), sig.params.as_slice());
            let mut untyped = Vec::new();
            self.function_body(&sig.py, source, &[], Some(guard), ret(false), &mut untyped);
            // J90-P2: when the guarded entry's own body is the typed body line for line (the
            // annotations proved nothing the lowering used), one body serves both names: the
            // entry without its guard, and the typed name bound to it.
            let guard_at = untyped
                .iter()
                .position(|l| l.starts_with("    if ") && l.ends_with(':'))
                .filter(|&k| {
                    untyped.get(k + 1).is_some_and(|l| {
                        l.starts_with(&format!("        return {}(", sig.typed_py))
                    })
                });
            // J90-P3: line for line up to the compiler's own temporaries (`_js_caught3` in one
            // body, `_js_caught9` in the other): each is local to its body, so renaming them
            // consistently changes nothing the body does.
            let same = guard_at.is_some_and(|k| {
                let typed = &out[typed_at..];
                let head = |l: &str, name: &str| {
                    l.strip_prefix(&format!("def {name}(")).map(str::to_string)
                };
                let a: Vec<&String> = typed[1..k].iter().chain(&typed[k..]).collect();
                let b: Vec<&String> = untyped[1..k].iter().chain(&untyped[k + 2..]).collect();
                typed.len() + 2 == untyped.len()
                    && head(&typed[0], &sig.typed_py).is_some()
                    && head(&typed[0], &sig.typed_py) == head(&untyped[0], &sig.py)
                    && canonical_temps(&a) == canonical_temps(&b)
            });
            if let Some(k) = guard_at.filter(|_| same) {
                out.truncate(typed_at);
                untyped.drain(k..k + 2);
                out.extend(untyped);
                out.push(String::new());
                out.push(String::new());
                out.push(format!("{} = {}", sig.typed_py, sig.py));
            } else {
                out.push(String::new());
                out.push(String::new());
                out.extend(untyped);
            }
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
                // J89-4a: a module `function*` lowers to a Python generator function.
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
        let generator = matches!(source, FnSource::Decl(f) if f.generator);
        let saved_generator = std::mem::replace(&mut self.in_generator, generator);
        let saved_yields = std::mem::replace(&mut self.yields, 0);
        let saved_try = std::mem::replace(&mut self.try_depth, 0);
        if generator {
            // Its call answers a generator object, of which nothing is proven.
            self.observed.observe(ret.clone(), Fact::default());
        }
        self.push_scope(locals, owner);
        self.rets.push(Some(ret.clone()));
        self.bind_params(params, facts);
        out.push(format!("def {name}({}):", join_params(&names)));
        let def_at = out.len();
        self.global_writes.push(BTreeSet::new());
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
                if generator {
                    // J89-4a: a body with no `yield` is still a generator, as `function*` is.
                    if self.yields == 0 {
                        if !ends_in_exit(statements) {
                            out.push("    return".to_string());
                        }
                        out.push("    yield  # a function* is a generator".to_string());
                    }
                } else if !ends_in_exit(statements) {
                    // J86: a body that can run off its end returns `undefined`, as JS does
                    // (Python: `None`).
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
        let writes = self.global_writes.pop().unwrap_or_default();
        if !writes.is_empty() {
            let names: Vec<String> = writes.iter().map(|n| self.globals[n].clone()).collect();
            out.insert(def_at, format!("    global {}", names.join(", ")));
        }
        self.rets.pop();
        self.pop_scope();
        self.in_generator = saved_generator;
        self.yields = saved_yields;
        self.try_depth = saved_try;
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
        let seal = self.seal.take();
        // J87-3: what a `catch` binding holds may be a Python exception (an adapter's OSError),
        // whose properties JS would read differently; only rethrowing it is accepted.
        // J88-2: read as a value, it is what was caught; the runtime answers only what JS would
        // read of it (`_js_get`: an fs error's `code`, a JS Error's own properties) and refuses
        // the rest.
        if let Some((_, caught)) = self.catch_params.iter().rev().find(|(n, _)| n == name) {
            return Py::atom(caught.clone());
        }
        if self.scopes.iter().rev().any(|scope| scope.contains(name)) {
            self.seal_read(name, seal);
            // J89-3: a Float64Array is only indexed, written by index and measured; any other
            // read would hand its list of floats to code that takes it for a plain array.
            if self
                .var_key(name)
                .is_some_and(|key| self.typed_arrays.contains(&key))
            {
                return self.refuse(
                    span,
                    "a Float64Array used as a value (only t[i], t[i] = v and t.length are accepted)",
                );
            }
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

    /// J91-3 (#341): the next identifier lowered, `e` itself when it names a local, is read in a
    /// sealed use of this kind. Anything but a local name is not marked (its reads are its own).
    fn seal_next(&mut self, e: &Expression<'_>, kind: Seal) {
        if let Expression::Identifier(id) = strip(e)
            && self.is_scoped(id.name.as_str())
        {
            self.seal = Some(kind);
        }
    }

    /// J91-3 (#341): note a read of the local `name` (`seal`: the sealed use it is, if any): the
    /// nested functions it is read from (`Assume::captured`), and, unless the read is a sealed use,
    /// that its value escapes (`Assume::unsealed`).
    fn seal_read(&mut self, name: &str, seal: Option<Seal>) {
        let Some(i) = self.scopes.iter().rposition(|s| s.contains(name)) else {
            return;
        };
        let Some(key) = self.var_key(name) else {
            return;
        };
        let declared_in = self.scope_owner[i];
        let here = self.scope_owner.last().copied();
        if here != Some(declared_in) {
            let nested: BTreeSet<u32> = self.scope_owner[i + 1..]
                .iter()
                .copied()
                .filter(|o| *o != declared_in)
                .collect();
            self.observed
                .captured
                .entry(key.clone())
                .or_default()
                .extend(nested);
        }
        let sealed = match seal {
            Some(Seal::Use) => true,
            Some(Seal::Return) => here == Some(declared_in) && self.returnable(&key),
            Some(Seal::Call) => here == Some(declared_in),
            None => false,
        };
        if !sealed {
            self.observed.unsealed.insert(key);
        }
    }

    /// J91-3 (#341): every nested function that reads `key` is a sealed closure (`const f = (...)
    /// => ...` whose every read is a direct call from the body that declares it), so none can run
    /// once that body has returned: a `return` of the value hands the caller the only reference.
    fn returnable(&self, key: &Key) -> bool {
        self.assume.captured.get(key).is_none_or(|owners| {
            owners.iter().all(|owner| {
                self.assume
                    .closures
                    .get(owner)
                    .is_some_and(|f| !self.assume.unsealed.contains(f))
            })
        })
    }

    /// J91-3 (#341): `x.push(...)`, `x.set(k, v)` or `x.add(v)` on the local `const` `x`: what it
    /// now holds, met into its binding's fact (a meet only weakens it, so a call on anything
    /// else costs nothing but facts).
    fn fill(&mut self, object: &Expression<'_>, fact: Fact) {
        if let Expression::Identifier(id) = strip(object)
            && self.is_scoped(id.name.as_str())
            && let Some(key) = self.var_key(id.name.as_str())
            && self.consts.contains(&key)
        {
            self.observed.observe(key, fact);
        }
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
            // J91-3 (#341): an `own` list, Map or Set's `elem` is what it holds, not property values.
            Some(value) if !object.is_list && !object.top && !object.own => Py {
                nn: Some(Box::new(value.shallow())),
                no_null: value.never_null(),
                ..read
            },
            _ => read,
        }
    }

    /// J89-3: the source name of the Float64Array binding `e` names, if it names one.
    fn typed_array(&self, e: &Expression<'_>) -> Option<String> {
        let Expression::Identifier(id) = strip(e) else {
            return None;
        };
        let name = id.name.as_str();
        if !self.is_scoped(name) {
            return None;
        }
        let key = self.var_key(name)?;
        self.typed_arrays.contains(&key).then(|| name.to_string())
    }

    /// J89-3: in the proven copy of a counted loop, `e` is its loop variable.
    fn is_fast_index(&self, e: &Expression<'_>) -> bool {
        matches!((strip(e), &self.fast), (Expression::Identifier(id), Some(fast)) if id.name == fast.var.as_str())
    }

    /// J90-P3: `e` may be evaluated twice: a local name, or a literal index into one (a read
    /// of a list or a dict element runs no code).
    fn twice_safe(&self, e: &Expression<'_>) -> bool {
        match strip(e) {
            Expression::Identifier(id) => self.is_scoped(id.name.as_str()),
            Expression::ComputedMemberExpression(m) => {
                matches!(strip(&m.object), Expression::Identifier(id) if self.is_scoped(id.name.as_str()))
                    && matches!(strip(&m.expression), Expression::NumericLiteral(_))
            }
            _ => false,
        }
    }

    /// J90-P3: `c` when `e` is `var + c` (or `var` itself, 0), `c` a whole-number literal or a
    /// module `const` bound to one.
    fn index_offset(&self, e: &Expression<'_>, var: &str) -> Option<u64> {
        match strip(e) {
            Expression::Identifier(id) if id.name == var => Some(0),
            Expression::BinaryExpression(b) if b.operator == BinaryOperator::Addition => {
                if !matches!(strip(&b.left), Expression::Identifier(x) if x.name == var) {
                    return None;
                }
                self.int_literal(&b.right)
            }
            _ => None,
        }
    }

    /// J90-P3: a whole-number literal from 0 to 1024, or a module `const` bound to one.
    fn int_literal(&self, e: &Expression<'_>) -> Option<u64> {
        match strip(e) {
            Expression::NumericLiteral(n)
                if n.value >= 0.0 && n.value.fract() == 0.0 && n.value <= 1024.0 =>
            {
                Some(n.value as u64)
            }
            Expression::Identifier(id) if !self.is_scoped(id.name.as_str()) => {
                self.int_consts.get(id.name.as_str()).copied()
            }
            _ => None,
        }
    }

    /// J90-P3: in the proven copy of a counted loop, the offset `c` of an index `i + c` (0 for
    /// `i` itself) into an array the copy reads directly.
    fn fast_offset(&self, e: &Expression<'_>) -> Option<u64> {
        let fast = self.fast.as_ref()?;
        self.index_offset(e, &fast.var)
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
        // J88-2: an arrow function used as a value inside this statement is a nested `def`
        // emitted just before it (`pre`); a statement nested inside keeps its own.
        let start = out.len();
        let saved_pre = std::mem::take(&mut self.pre);
        let saved_indent = std::mem::replace(&mut self.cur_indent, indent);
        self.stmt_inner(s, indent, out);
        self.cur_indent = saved_indent;
        let pre = std::mem::replace(&mut self.pre, saved_pre);
        if !pre.is_empty() {
            out.splice(start..start, pre);
        }
    }

    fn stmt_inner(&mut self, s: &Statement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        match s {
            Statement::ExpressionStatement(e) => match &e.expression {
                Expression::AssignmentExpression(a) => self.assignment(a, indent, out),
                // J89-4a: `yield <value>;` in a module generator: Python's `yield`, whose value
                // (what a `next(v)` would send) is discarded as the statement discards it.
                // Not inside a `try`: a `break` out of a JS `for-of` closes the generator at once
                // (its `finally` runs, no `catch` sees it), where Python closes it when it is
                // collected, with a GeneratorExit raised at the `yield`.
                Expression::YieldExpression(y)
                    if self.in_generator
                        && !y.delegate
                        && y.argument.is_some()
                        && self.try_depth == 0 =>
                {
                    let arg = y.argument.as_ref().expect("checked above");
                    let value = self.expr(arg);
                    self.yields += 1;
                    out.push(format!("{p}yield {}", value.code));
                }
                Expression::UpdateExpression(u) => {
                    self.refuse(u.span, "update expression (++/--)");
                }
                other => {
                    self.statement_call = matches!(other, Expression::CallExpression(_));
                    // J90-PF: the call's statement form first; else `expr`'s own (`hot`).
                    let since = self.fact_seq;
                    let value = self.expr_inner(other);
                    self.statement_call = false;
                    match self.hot_stmt(&value.code, &p, since) {
                        Some(lines) => out.extend(lines),
                        None => {
                            let value = self.hot(value, since);
                            out.push(format!("{p}{}", value.code));
                        }
                    }
                }
            },
            Statement::VariableDeclaration(v) => self.var_decl(v, indent, out),
            // J89-4a: in a generator, `return;` ends it; a value it would return is refused (no
            // compiled consumer reads it).
            Statement::ReturnStatement(r) if self.in_generator => {
                if r.argument.is_some() {
                    self.refuse(r.span, "return with a value in a generator function");
                } else {
                    out.push(format!("{p}return"));
                }
            }
            Statement::ReturnStatement(r) => match &r.argument {
                Some(arg) => {
                    // J91-3 (#341): `return x` hands the caller `x` (`Seal::Return`).
                    self.seal_next(arg, Seal::Return);
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

    /// J89-2: `x++`, `++x`, `x--` or `--x` whose value is unused, `x` a local name: `x` becomes
    /// `_js_inc(x)` / `_js_dec(x)` (ToNumeric, then plus or minus one: a string `"1"` becomes 2,
    /// where `x += 1` would concatenate), or `_js_num(x + 1)` when `x` is proven a number.
    fn update_stmt(&mut self, u: &UpdateExpression<'_>, indent: usize, out: &mut Vec<String>) {
        let SimpleAssignmentTarget::AssignmentTargetIdentifier(id) = &u.argument else {
            self.refuse(u.span, "update of anything but a local name");
            return;
        };
        let target = self.local_target(id.name.as_str(), id.span);
        if !target.is_num {
            self.check_carried(id.name.as_str(), &target);
        }
        let plus = u.operator == UpdateOperator::Increment;
        let code = if target.is_num {
            format!(
                "_js_num({} {} 1)",
                target.code,
                if plus { "+" } else { "-" }
            )
        } else {
            format!(
                "{}({})",
                if plus { "_js_inc" } else { "_js_dec" },
                target.code
            )
        };
        out.push(format!("{}{} = {code}", pad(indent), target.code));
    }

    /// J87-3: `for (let i = a; test; i -= 1) body` -> `i = a` / `while test:` / body / update. The
    /// init must be a `let` declaration (or absent), the update an assignment (or absent). A
    /// `continue` that would leave the body is refused: in JS it runs the update, and a Python
    /// `continue` would skip it. Closures in the body are refused as in any loop.
    fn c_for(&mut self, f: &ForStatement<'_>, indent: usize, out: &mut Vec<String>) {
        // J89-3: a counted loop over arrays it indexes by its variable gets a proven copy.
        if let Some(plan) = self.fast_loop_plan(f) {
            let Some(ForStatementInit::VariableDeclaration(v)) = &f.init else {
                unreachable!("fast_loop_plan matched a let init")
            };
            self.var_decl(v, indent, out);
            self.fast_loop(f, plan, indent, out);
            return;
        }
        self.c_for_loop(f, indent, out);
    }

    /// `c_for` after its init: the loop itself.
    fn c_for_loop(&mut self, f: &ForStatement<'_>, indent: usize, out: &mut Vec<String>) {
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
            Some(ForStatementInit::VariableDeclaration(_)) if self.fast_init_done => {
                self.fast_init_done = false;
            }
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
        // J89-2: `i++` / `++i` / `i--` / `--i` as the update (its value unused): `i` becomes
        // ToNumeric(i) + 1 (- 1), never a string concatenation (`_js_inc`).
        enum Update<'b, 'a> {
            Inc(&'b UpdateExpression<'a>),
            Assign(&'b AssignmentExpression<'a>),
        }
        let update = match &f.update {
            None => None,
            Some(Expression::UpdateExpression(u)) => Some(Update::Inc(u)),
            Some(Expression::AssignmentExpression(a)) => Some(Update::Assign(a)),
            Some(other) => {
                self.refuse(
                    other.span(),
                    "C-style for loop update other than an assignment",
                );
                return;
            }
        };
        let test = match &f.test {
            Some(test) => self.condition(test),
            None => "True".to_string(),
        };
        // J91-1 (#341): a counted loop's variable is an index in its body (`counter`), and its
        // update is Python's int `+` of the stride.
        let counter = self.counter(f);
        let narrowed = self.narrow.len();
        if let Some((key, _, _, _)) = &counter {
            self.narrow.push((key.clone(), Fact::idx()));
        }
        if !continues_out(&f.body) {
            out.push(format!("{p}while {test}:"));
            self.breaks.push(BreakTarget::Loop);
            self.body(&f.body, indent + 1, out);
            self.breaks.pop();
            self.narrow.truncate(narrowed);
            match (&counter, update) {
                (Some((_, name, step, span)), _) => {
                    self.counter_step(name, *step, *span, indent + 1, out)
                }
                (None, Some(Update::Inc(u))) => self.update_stmt(u, indent + 1, out),
                (None, Some(Update::Assign(a))) => self.assignment(a, indent + 1, out),
                (None, None) => {}
            }
            return;
        }
        // J89-4a: a `continue` that leaves the body runs the update and then the test, as JS's
        // `for` does. The update moves to the top of every iteration but the first, so a Python
        // `continue` reaches it: `first = True` / `while True:` / `if first: first = False` /
        // `else: <update>` / `if not (<test>): break` / the body.
        let first = format!("_js_first{}", self.tmp);
        self.tmp += 1;
        let (inner, deep) = (pad(indent + 1), pad(indent + 2));
        let mut body = Vec::new();
        self.breaks.push(BreakTarget::Loop);
        self.body(&f.body, indent + 1, &mut body);
        self.breaks.pop();
        self.narrow.truncate(narrowed);
        let mut step = Vec::new();
        match (&counter, update) {
            (Some((_, name, stride, span)), _) => {
                self.counter_step(name, *stride, *span, indent + 2, &mut step)
            }
            (None, Some(Update::Inc(u))) => self.update_stmt(u, indent + 2, &mut step),
            (None, Some(Update::Assign(a))) => self.assignment(a, indent + 2, &mut step),
            (None, None) => {}
        }
        if step.is_empty() {
            step.push(format!("{deep}pass"));
        }
        out.push(format!("{p}{first} = True"));
        out.push(format!("{p}while True:"));
        out.push(format!("{inner}if {first}:"));
        out.push(format!("{deep}{first} = False"));
        out.push(format!("{inner}else:"));
        out.extend(step);
        if test != "True" {
            out.push(format!("{inner}if not ({test}):"));
            out.push(format!("{deep}break"));
        }
        out.extend(body);
    }

    /// J91-1 (#341): `for (let i = L; i < B; i += S)` (or `i = i + S`, `i++`, `++i`) is a COUNTED
    /// loop when `L` is a whole literal in `[0, IDX_MAX]`, `S` a whole literal in `[1, 2**20]`, `B`
    /// an expression `idx_bound` proves an index wherever the test reads it, and the update is the
    /// only assignment to `i` inside the statement (`Assume::assign_spans`; the `let` is scoped to
    /// the statement, so the body, its closures and the test assign it nowhere). Then in the body `0 <= i < B <= IDX_MAX`: `i` starts at `L >= 0`,
    /// only the update moves it, upward, and the body runs only where the test just held. `i` is an
    /// int throughout (an int literal, then an int plus an int), and the update's `i + S` is at most
    /// `IDX_MAX - 1 + 2**20 < 2**53`, so Python's int `+` is the double sum JS computes. The key,
    /// source name, stride and the update target's span start.
    fn counter(&mut self, f: &ForStatement<'_>) -> Option<(Key, String, u64, u32)> {
        let Some(ForStatementInit::VariableDeclaration(v)) = &f.init else {
            return None;
        };
        if v.kind != VariableDeclarationKind::Let || v.declarations.len() != 1 {
            return None;
        }
        let d = &v.declarations[0];
        let BindingPattern::BindingIdentifier(id) = &d.id else {
            return None;
        };
        let name = id.name.as_str();
        let whole = |e: &Expression<'_>, lo: f64, hi: f64| {
            matches!(strip(e), Expression::NumericLiteral(n)
                if n.value.fract() == 0.0 && n.value >= lo && n.value <= hi)
        };
        if !d
            .init
            .as_ref()
            .is_some_and(|e| whole(e, 0.0, crate::types::IDX_MAX as f64))
        {
            return None;
        }
        let Some(Expression::BinaryExpression(test)) = f.test.as_ref().map(strip) else {
            return None;
        };
        if test.operator != BinaryOperator::LessThan
            || !matches!(strip(&test.left), Expression::Identifier(l) if l.name == name)
            || !self.idx_bound(&test.right)
        {
            return None;
        }
        let is_var =
            |e: &Expression<'_>| matches!(strip(e), Expression::Identifier(x) if x.name == name);
        let stride = |e: &Expression<'_>| -> Option<u64> {
            whole(e, 1.0, (1u64 << 20) as f64).then(|| match strip(e) {
                Expression::NumericLiteral(n) => n.value as u64,
                _ => unreachable!("whole matched a literal"),
            })
        };
        let (step, span) = match f.update.as_ref()? {
            Expression::UpdateExpression(u) if u.operator == UpdateOperator::Increment => {
                match &u.argument {
                    SimpleAssignmentTarget::AssignmentTargetIdentifier(x) if x.name == name => {
                        (1, x.span.start)
                    }
                    _ => return None,
                }
            }
            Expression::AssignmentExpression(a) => {
                let AssignmentTarget::AssignmentTargetIdentifier(x) = &a.left else {
                    return None;
                };
                if x.name != name {
                    return None;
                }
                let step = match a.operator {
                    AssignmentOperator::Addition => stride(&a.right)?,
                    AssignmentOperator::Assign => match strip(&a.right) {
                        Expression::BinaryExpression(b)
                            if b.operator == BinaryOperator::Addition && is_var(&b.left) =>
                        {
                            stride(&b.right)?
                        }
                        _ => return None,
                    },
                    _ => return None,
                };
                (step, x.span.start)
            }
            _ => return None,
        };
        // The `let` of a `for` is visible only inside the statement, so an assignment to this
        // binding lies inside its span; one there to another binding of the name (a nested `let i`
        // shares the function's key) only makes the test fail, which is safe.
        let key = self.var_key(name)?;
        let (lo, hi) = (f.span.start, f.span.end);
        let only = self.assume.assign_spans.get(&key).is_some_and(|spans| {
            let inside: Vec<u32> = spans.range(lo..hi).copied().collect();
            inside == [span]
        });
        only.then(|| (key, name.to_string(), step, span))
    }

    /// J91-1: a counted loop's bound is an index wherever the test reads it: a whole literal in
    /// `[0, IDX_MAX]`, a name (local or module `const`) proven one, or `.length` of a name proven a
    /// list or a `str` (`len_idx`). A binding's fact holds at every read, the test's included.
    fn idx_bound(&mut self, e: &Expression<'_>) -> bool {
        let fact_of = |me: &mut Self, name: &str| -> Option<Fact> {
            let key = me.var_key(name)?;
            me.current(&key).filter(|f| !f.top)
        };
        match strip(e) {
            Expression::NumericLiteral(n) => {
                n.value.fract() == 0.0 && n.value >= 0.0 && n.value <= crate::types::IDX_MAX as f64
            }
            Expression::Identifier(id) => fact_of(self, id.name.as_str()).is_some_and(|f| f.idx),
            Expression::StaticMemberExpression(m) if m.property.name == "length" => {
                match strip(&m.object) {
                    Expression::Identifier(id) if self.typed_array(&m.object).is_none() => {
                        fact_of(self, id.name.as_str()).is_some_and(|f| f.list || f.str_)
                    }
                    _ => false,
                }
            }
            _ => false,
        }
    }

    /// J91-1: a counted loop's update, `i = i + S` (Python's int `+`; `counter` proves it exact),
    /// recorded as the assignment it is (`local_target`) of a safe int.
    fn counter_step(
        &mut self,
        name: &str,
        step: u64,
        span: u32,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        let target = self.local_target(name, Span::new(span, span));
        self.bind(name, Fact::int());
        out.push(format!(
            "{}{} = {} + {step}",
            pad(indent),
            target.code,
            target.code
        ));
    }

    /// J89-3: `for (let i = a; i < b; i += 1) body` (or `i++` / `++i`) whose body can be proven
    /// to index arrays only in range and read only numbers from them, given a check made once
    /// before the loop: `i` is an int with `0 <= i`, `b` an int no larger than the length of every
    /// array the body indexes by `i`, each plain array so read holds proven numbers over `[i, b)`
    /// (`_js_doubles`), and each `const` or parameter the body uses as an operand of arithmetic or a
    /// comparison is a proven number. Nothing in the body may change any of that: it assigns
    /// neither `i`, nor `b`, nor those arrays, writes only Float64Array elements at `i` and locals,
    /// pushes only onto fresh local arrays, and calls only adapters and `Math` functions (so no
    /// compiled or caller code runs while it loops); no closure, no other member read, no nested
    /// loop. `None`: the loop is lowered once, as before.
    fn fast_loop_plan(&mut self, f: &ForStatement<'_>) -> Option<LoopPlan> {
        if self.in_fallback > 0 {
            return None;
        }
        let Some(ForStatementInit::VariableDeclaration(v)) = &f.init else {
            return None;
        };
        if v.kind != VariableDeclarationKind::Let || v.declarations.len() != 1 {
            return None;
        }
        let d = &v.declarations[0];
        let BindingPattern::BindingIdentifier(id) = &d.id else {
            return None;
        };
        d.init.as_ref()?;
        let var = id.name.to_string();
        // The test: `i < b`.
        let Some(Expression::BinaryExpression(test)) = f.test.as_ref().map(strip) else {
            return None;
        };
        if test.operator != BinaryOperator::LessThan
            || !matches!(strip(&test.left), Expression::Identifier(l) if l.name == var.as_str())
        {
            return None;
        }
        // The update: `i += 1`, `i = i + 1`, `i++`, `++i`; J90-P3: or a stride `i += S` /
        // `i = i + S`, `S` a positive whole-number literal or a module `const` bound to one.
        let stride = |e: &Expression<'_>| self.int_literal(e).filter(|s| *s >= 1);
        let is_var = |e: &Expression<'_>| matches!(strip(e), Expression::Identifier(x) if x.name == var.as_str());
        let step = match f.update.as_ref() {
            Some(Expression::UpdateExpression(u))
                if u.operator == UpdateOperator::Increment
                    && matches!(&u.argument, SimpleAssignmentTarget::AssignmentTargetIdentifier(x) if x.name == var.as_str()) =>
            {
                Some(1)
            }
            Some(Expression::AssignmentExpression(a)) if matches!(&a.left, AssignmentTarget::AssignmentTargetIdentifier(x) if x.name == var.as_str()) => {
                match a.operator {
                    AssignmentOperator::Addition => stride(&a.right),
                    AssignmentOperator::Assign => match strip(&a.right) {
                        Expression::BinaryExpression(b)
                            if b.operator == BinaryOperator::Addition && is_var(&b.left) =>
                        {
                            stride(&b.right)
                        }
                        _ => None,
                    },
                    _ => None,
                }
            }
            _ => None,
        };
        let step = step?;
        let mut scan = LoopScan {
            var: var.clone(),
            ..LoopScan::default()
        };
        if !self.scan_stmt(&f.body, &mut scan) || scan.assigned.contains(&var) {
            return None;
        }
        // The bound: a name the body does not assign, a literal, or a Float64Array's length.
        let (bound, bound_name) = match strip(&test.right) {
            Expression::Identifier(b) => {
                let name = b.name.to_string();
                if name == var
                    || scan.assigned.contains(&name)
                    || scan.declared.contains(&name)
                    || !(self.is_scoped(&name) || self.module_consts.contains(&name))
                    || self.typed_array(&test.right).is_some()
                {
                    return None;
                }
                let py = if self.is_scoped(&name) {
                    py_name(&name, false, false)
                } else {
                    self.globals.get(&name)?.clone()
                };
                (py, Some(py_name(&name, false, false)))
            }
            Expression::NumericLiteral(n) if n.value >= 0.0 && n.value.fract() == 0.0 => {
                (py_number(n.value)?, None)
            }
            Expression::StaticMemberExpression(m) if m.property.name == "length" => {
                let name = self.typed_array(&m.object)?;
                (format!("len({})", py_name(&name, false, false)), None)
            }
            _ => return None,
        };
        for x in &scan.plain {
            if scan.assigned.contains(x)
                || scan.declared.contains(x)
                || scan.pushed.contains(x)
                || scan.filled.contains(x)
                || !self.is_scoped(x)
            {
                return None;
            }
        }
        for x in &scan.filled {
            if scan.assigned.contains(x) || scan.declared.contains(x) || scan.pushed.contains(x) {
                return None;
            }
        }
        // J90-P: an array whose `.length` the body reads keeps that length through the loop: the
        // body neither assigns it nor pushes onto it nor stores past its end, and calls no code
        // that could (adapters and `Math` only).
        for x in &scan.measured {
            if *x == var
                || scan.assigned.contains(x)
                || scan.declared.contains(x)
                || scan.pushed.contains(x)
                || scan.filled.contains(x)
                || !self.is_scoped(x)
            {
                return None;
            }
        }
        // Each operand name the body neither declares nor assigns is checked a number before the
        // loop, unless it is one already.
        let mut speculated = Vec::new();
        let mut carried = Vec::new();
        for name in &scan.numeric {
            if *name == var || scan.declared.contains(name) || !self.is_scoped(name) {
                continue;
            }
            if scan.assigned.contains(name) {
                carried.push(name.clone());
                continue;
            }
            let key = self.var_key(name)?;
            let proven = self.current(&key).is_some_and(|f| f.num && !f.top);
            if !proven {
                speculated.push(name.clone());
            }
        }
        if scan.typed.is_empty()
            && scan.plain.is_empty()
            && scan.filled.is_empty()
            && speculated.is_empty()
        {
            return None;
        }
        // J90-P3: an array read only as a value is bounds-checked alone (its elements may be
        // anything: each read proves nothing about its element).
        let (plain, pass): (BTreeSet<String>, BTreeSet<String>) = scan
            .plain
            .into_iter()
            .partition(|x| scan.numeric_arrays.contains(x));
        Some(LoopPlan {
            var,
            bound,
            bound_name,
            typed: scan.typed.into_iter().collect(),
            plain,
            filled: scan.filled.into_iter().collect(),
            measured: scan.measured.into_iter().collect(),
            step,
            offsets: scan.offsets.into_iter().collect(),
            pass,
            speculated,
            carried,
            declared: scan.declared,
        })
    }

    /// J89-3: the counted loop `plan` describes, twice: under its guard, as a Python `for` over a
    /// `range` whose body reads and writes the arrays directly (the proven copy, lowered under the
    /// facts the guard checked); otherwise the general loop `c_for_loop` lowers, unchanged. The
    /// init is already emitted.
    fn fast_loop(
        &mut self,
        f: &ForStatement<'_>,
        plan: LoopPlan,
        indent: usize,
        out: &mut Vec<String>,
    ) {
        let start = out.len();
        let refusals = self.refusals.len();
        if plan.carried.is_empty() || !self.fast_copy(f, &plan, true, indent, out) {
            out.truncate(start);
            self.fast_copy(f, &plan, false, indent, out);
        }
        // A refusal in the copy is one the general loop below records too.
        self.refusals.truncate(refusals);
        out.push(format!("{}else:", pad(indent)));
        self.fast_init_done = true;
        self.in_fallback += 1;
        self.c_for_loop(f, indent + 1, out);
        self.in_fallback -= 1;
        self.fast_init_done = false;
    }

    /// J89-3: the guard and the proven copy of `fast_loop`. With `carry`, the outer `let`s the body
    /// assigns are checked numbers before the loop too and read as numbers inside it; false when an
    /// assignment in the copy then gives one a value not proven a number (the caller lowers the
    /// copy again without them).
    fn fast_copy(
        &mut self,
        f: &ForStatement<'_>,
        plan: &LoopPlan,
        carry: bool,
        indent: usize,
        out: &mut Vec<String>,
    ) -> bool {
        let p = pad(indent);
        let i = py_name(&plan.var, false, false);
        let b = plan.bound.clone();
        let mut guard = vec![format!("type({i}) is int"), format!("0 <= {i}")];
        if plan.bound_name.is_some() {
            guard.push(format!("type({b}) is int"));
        }
        for t in &plan.typed {
            guard.push(format!("{b} <= len({})", py_name(t, false, false)));
        }
        // J90-P3: the last index a read `x[i + c]` reaches is `last + c`, `last` the largest
        // value `range(i, b, step)` takes (none when `b <= i`).
        let step = plan.step;
        let in_range = |x: &str, c: u64| -> String {
            if step == 1 {
                if c == 0 {
                    format!("{b} <= len({x})")
                } else {
                    format!("{b} + {c} <= len({x})")
                }
            } else {
                let plus = if c == 0 {
                    String::new()
                } else {
                    format!(" + {c}")
                };
                format!("({b} <= {i} or {i} + ({b} - 1 - {i}) // {step} * {step}{plus} < len({x}))")
            }
        };
        for x in &plan.plain {
            let c = plan.offsets.get(x).copied().unwrap_or(0);
            let x = py_name(x, false, false);
            guard.push(format!("type({x}) is list"));
            guard.push(in_range(&x, c));
            if step == 1 && c == 0 {
                guard.push(format!("_js_doubles({x}, {i}, {b})"));
            } else if step == 1 {
                guard.push(format!("_js_doubles({x}, {i}, {b} + {c})"));
            } else {
                guard.push(format!("_js_doubles({x}, {i}, len({x}))"));
            }
        }
        for x in &plan.pass {
            let c = plan.offsets.get(x).copied().unwrap_or(0);
            let x = py_name(x, false, false);
            guard.push(format!("type({x}) is list"));
            guard.push(in_range(&x, c));
        }
        for x in &plan.filled {
            let x = py_name(x, false, false);
            guard.push(format!("type({x}) is list"));
            guard.push(format!("{b} <= len({x})"));
        }
        for x in plan
            .measured
            .iter()
            .filter(|x| !plan.plain.contains(*x) && !plan.filled.contains(*x))
        {
            guard.push(format!("type({}) is list", py_name(x, false, false)));
        }
        let carried: Vec<String> = if carry {
            plan.carried.clone()
        } else {
            Vec::new()
        };
        for v in plan.speculated.iter().chain(&carried) {
            guard.push(format!("_js_is_double({})", py_name(v, false, false)));
        }
        out.push(format!("{p}if {}:", guard.join(" and ")));
        // The loop starts at the value the init gave `i` (a Python `range` reads it once).
        let stride = if step == 1 {
            String::new()
        } else {
            format!(", {step}")
        };
        out.push(format!(
            "{}for {i} in range({i}, {b}{stride}):  # noqa: B020",
            pad(indent + 1)
        ));
        let saved = self.fast.replace(FastLoop {
            span: f.span.start,
            declared: plan.declared.clone(),
            var: plan.var.clone(),
            typed: plan.typed.iter().cloned().collect(),
            plain: plan.plain.iter().cloned().collect(),
            pass: plan.pass.iter().cloned().collect(),
            filled: plan.filled.iter().cloned().collect(),
            carried: carried.iter().cloned().collect(),
        });
        if let Some(outer) = saved.clone() {
            self.fast_outer.push(outer);
        }
        let depth = self.narrow.len();
        let mut narrowed = vec![plan.var.clone()];
        narrowed.extend(plan.speculated.iter().cloned());
        narrowed.extend(carried.iter().cloned());
        for name in &narrowed {
            if let Some(key) = self.var_key(name) {
                self.narrow.push((key, Fact::num()));
            }
        }
        // J90-P: each array whose `.length` the body reads is a list there (the guard checked it,
        // and the body cannot rebind it), so `.length` is `len(...)`.
        for name in &plan.measured {
            if let Some(key) = self.var_key(name) {
                self.narrow.push((key, Fact::list()));
            }
        }
        let failed = std::mem::replace(&mut self.fast_carry_failed, false);
        self.breaks.push(BreakTarget::Loop);
        self.body(&f.body, indent + 2, out);
        self.breaks.pop();
        // J90-P3: a nested copy that assigns a carried `let` a value not proven a number does not
        // flag it here, but the nested loop's general loop (lowered in this copy too) does.
        let ok = !std::mem::replace(&mut self.fast_carry_failed, failed);
        self.narrow.truncate(depth);
        if saved.is_some() {
            self.fast_outer.pop();
        }
        self.fast = saved;
        ok
    }

    /// J89-3: in the proven copy of a counted loop, `name` (assigned `value`) is a carried `let`:
    /// the copy holds only if `value` is a proven number.
    fn check_carried(&mut self, name: &str, value: &Py) {
        if self.fast.as_ref().is_some_and(|f| f.carried.contains(name))
            && !(value.is_num && value.is_double)
        {
            self.fast_carry_failed = true;
        }
    }

    /// J89-3: `fast_loop_plan`'s walk of a statement of the loop body; false for anything outside
    /// what a proven copy may hold.
    fn scan_stmt(&self, s: &Statement<'_>, sc: &mut LoopScan) -> bool {
        match s {
            Statement::BlockStatement(b) => b.body.iter().all(|s| self.scan_stmt(s, sc)),
            Statement::EmptyStatement(_) => true,
            Statement::BreakStatement(b) => b.label.is_none(),
            Statement::ReturnStatement(r) => r
                .argument
                .as_ref()
                .is_none_or(|e| self.scan_expr(e, sc, false)),
            // J90-P3: `throw new Error('...')`: it leaves the loop and runs no compiled code.
            Statement::ThrowStatement(t) => match strip(&t.argument) {
                Expression::NewExpression(n) => {
                    matches!(strip(&n.callee), Expression::Identifier(id) if id.name == "Error" && !self.is_local("Error"))
                        && n.arguments.iter().all(|a| {
                            matches!(
                                a.as_expression().map(strip),
                                Some(Expression::StringLiteral(_))
                            )
                        })
                }
                _ => false,
            },
            // J90-P3: a counted loop nested in the body (`for (let k = a; k < b; k += S)`): its
            // variable and every binding it declares are the body's, and its own reads by `k` are
            // reads by a local (`scan_expr`); it gets its own proven copy when it is lowered.
            Statement::ForStatement(f) => {
                let Some(ForStatementInit::VariableDeclaration(v)) = &f.init else {
                    return false;
                };
                if v.kind != VariableDeclarationKind::Let || v.declarations.len() != 1 {
                    return false;
                }
                let d = &v.declarations[0];
                let BindingPattern::BindingIdentifier(id) = &d.id else {
                    return false;
                };
                if id.name.as_str() == sc.var || f.test.is_none() {
                    return false;
                }
                sc.declared.insert(id.name.to_string());
                sc.assigned.insert(id.name.to_string());
                sc.loop_vars.insert(id.name.to_string());
                let init_ok = d.init.as_ref().is_some_and(|e| self.scan_expr(e, sc, true));
                let update_ok = match f.update.as_ref() {
                    Some(Expression::AssignmentExpression(a)) => {
                        matches!(&a.left, AssignmentTarget::AssignmentTargetIdentifier(x) if x.name == id.name)
                            && self.scan_assign(a, sc)
                    }
                    Some(Expression::UpdateExpression(u)) => {
                        matches!(&u.argument, SimpleAssignmentTarget::AssignmentTargetIdentifier(x) if x.name == id.name)
                    }
                    _ => false,
                };
                init_ok
                    && update_ok
                    && f.test
                        .as_ref()
                        .is_some_and(|t| self.scan_expr(t, sc, false))
                    && self.scan_stmt(&f.body, sc)
            }
            Statement::IfStatement(i) => {
                // J90-P3: a bare name tested is a sink (`_js_truthy` runs no code).
                sc.sink = matches!(strip(&i.test), Expression::Identifier(_));
                self.scan_expr(&i.test, sc, false)
                    && self.scan_stmt(&i.consequent, sc)
                    && i.alternate.as_ref().is_none_or(|a| self.scan_stmt(a, sc))
            }
            Statement::VariableDeclaration(v) => {
                matches!(
                    v.kind,
                    VariableDeclarationKind::Let | VariableDeclarationKind::Const
                ) && v.declarations.iter().all(|d| {
                    let BindingPattern::BindingIdentifier(id) = &d.id else {
                        return false;
                    };
                    if id.name.as_str() == sc.var {
                        return false;
                    }
                    sc.declared.insert(id.name.to_string());
                    // J90-P3: a `const` read from `x[i + c]`: a later operand use of it is an
                    // operand use of `x`'s element.
                    if v.kind == VariableDeclarationKind::Const
                        && let Some(Expression::ComputedMemberExpression(m)) =
                            d.init.as_ref().map(strip)
                        && let Expression::Identifier(object) = strip(&m.object)
                        && self.index_offset(&m.expression, &sc.var).is_some()
                    {
                        sc.from_read
                            .insert(id.name.to_string(), object.name.to_string());
                        sc.sink = true;
                    }
                    d.init.as_ref().is_none_or(|e| self.scan_expr(e, sc, false))
                })
            }
            Statement::ExpressionStatement(x) => match strip(&x.expression) {
                Expression::AssignmentExpression(a) => self.scan_assign(a, sc),
                Expression::UpdateExpression(u) => match &u.argument {
                    SimpleAssignmentTarget::AssignmentTargetIdentifier(id) => {
                        sc.assigned.insert(id.name.to_string());
                        true
                    }
                    _ => false,
                },
                Expression::CallExpression(c) => self.scan_call(c, sc),
                _ => false,
            },
            _ => false,
        }
    }

    fn scan_assign(&self, a: &AssignmentExpression<'_>, sc: &mut LoopScan) -> bool {
        let numeric = a.operator != AssignmentOperator::Assign;
        match &a.left {
            AssignmentTarget::AssignmentTargetIdentifier(id) => {
                if !matches!(
                    a.operator,
                    AssignmentOperator::Assign
                        | AssignmentOperator::Addition
                        | AssignmentOperator::Subtraction
                        | AssignmentOperator::Multiplication
                ) {
                    return false;
                }
                sc.assigned.insert(id.name.to_string());
                self.scan_expr(&a.right, sc, numeric)
            }
            AssignmentTarget::ComputedMemberExpression(m) => {
                let at_var = matches!(strip(&m.expression), Expression::Identifier(x) if x.name == sc.var.as_str());
                if a.operator != AssignmentOperator::Assign || !at_var {
                    return false;
                }
                if let Some(name) = self.typed_array(&m.object) {
                    sc.typed.insert(name);
                    return self.scan_expr(&a.right, sc, true);
                }
                // A fresh local array's element at `i`, in range: a plain store.
                let Expression::Identifier(object) = strip(&m.object) else {
                    return false;
                };
                let name = object.name.as_str();
                if !self.is_scoped(name)
                    || !self
                        .var_key(name)
                        .is_some_and(|k| self.fresh_arrays.contains(&k))
                {
                    return false;
                }
                sc.filled.insert(name.to_string());
                self.scan_expr(&a.right, sc, false)
            }
            _ => false,
        }
    }

    fn scan_call(&self, c: &CallExpression<'_>, sc: &mut LoopScan) -> bool {
        if c.optional {
            return false;
        }
        let args_ok = |this: &Self, sc: &mut LoopScan, numeric: bool| {
            c.arguments.iter().all(|a| match a.as_expression() {
                Some(e) => this.scan_expr(e, sc, numeric),
                None => false,
            })
        };
        match strip(&c.callee) {
            Expression::Identifier(id)
                if self.adapter_fns.contains(id.name.as_str())
                    && !self.is_scoped(id.name.as_str()) =>
            {
                args_ok(self, sc, false)
            }
            Expression::StaticMemberExpression(m) => {
                let Expression::Identifier(object) = strip(&m.object) else {
                    return false;
                };
                let name = object.name.as_str();
                if name == "Math" && !self.is_local("Math") {
                    let pure = [
                        "max", "min", "abs", "floor", "ceil", "trunc", "round", "sign", "sqrt",
                    ];
                    return pure.contains(&m.property.name.as_str()) && args_ok(self, sc, true);
                }
                if m.property.name == "push"
                    && c.arguments.len() == 1
                    && self.is_scoped(name)
                    && self
                        .var_key(name)
                        .is_some_and(|k| self.fresh_arrays.contains(&k))
                {
                    sc.pushed.insert(name.to_string());
                    // J90-P3: the pushed value is a sink.
                    return c.arguments[0].as_expression().is_some_and(|e| {
                        sc.sink = true;
                        self.scan_expr(e, sc, false)
                    });
                }
                false
            }
            _ => false,
        }
    }

    /// `numeric`: `e` is an operand of arithmetic or a comparison (or a value stored into a
    /// Float64Array), so a name there is checked a number before the loop.
    fn scan_expr(&self, e: &Expression<'_>, sc: &mut LoopScan, numeric: bool) -> bool {
        use BinaryOperator as Op;
        let sink = std::mem::replace(&mut sc.sink, false);
        match e {
            Expression::NumericLiteral(_)
            | Expression::BooleanLiteral(_)
            | Expression::NullLiteral(_)
            | Expression::StringLiteral(_) => true,
            Expression::Identifier(id) => {
                let name = id.name.as_str();
                if self.typed_array(e).is_some() {
                    return false;
                }
                if numeric {
                    sc.numeric.insert(name.to_string());
                }
                if !sink && let Some(array) = sc.from_read.get(name) {
                    sc.numeric_arrays.insert(array.clone());
                }
                true
            }
            // J90-P3: an array literal's elements, each a sink (stored as it is).
            Expression::ArrayExpression(a) => a.elements.iter().all(|el| match el {
                ArrayExpressionElement::SpreadElement(_) | ArrayExpressionElement::Elision(_) => {
                    false
                }
                other => other.as_expression().is_some_and(|x| {
                    sc.sink = true;
                    self.scan_expr(x, sc, false)
                }),
            }),
            Expression::ParenthesizedExpression(x) => {
                sc.sink = sink;
                self.scan_expr(&x.expression, sc, numeric)
            }
            Expression::TSNonNullExpression(x) => {
                sc.sink = sink;
                self.scan_expr(&x.expression, sc, numeric)
            }
            Expression::TSAsExpression(x) => {
                sc.sink = sink;
                self.scan_expr(&x.expression, sc, numeric)
            }
            Expression::TSSatisfiesExpression(x) => {
                sc.sink = sink;
                self.scan_expr(&x.expression, sc, numeric)
            }
            Expression::BinaryExpression(b) => {
                let numeric_op = matches!(
                    b.operator,
                    Op::Addition
                        | Op::Subtraction
                        | Op::Multiplication
                        | Op::Division
                        | Op::Remainder
                        | Op::LessThan
                        | Op::LessEqualThan
                        | Op::GreaterThan
                        | Op::GreaterEqualThan
                );
                let eq = matches!(b.operator, Op::StrictEquality | Op::StrictInequality);
                (numeric_op || eq)
                    && self.scan_expr(&b.left, sc, numeric_op)
                    && self.scan_expr(&b.right, sc, numeric_op)
            }
            Expression::LogicalExpression(l) => {
                self.scan_expr(&l.left, sc, false) && self.scan_expr(&l.right, sc, false)
            }
            Expression::UnaryExpression(u) => match u.operator {
                UnaryOperator::LogicalNot => self.scan_expr(&u.argument, sc, false),
                UnaryOperator::UnaryNegation => self.scan_expr(&u.argument, sc, true),
                _ => false,
            },
            Expression::ConditionalExpression(c) => {
                self.scan_expr(&c.test, sc, false)
                    && self.scan_expr(&c.consequent, sc, numeric)
                    && self.scan_expr(&c.alternate, sc, numeric)
            }
            Expression::ComputedMemberExpression(m) => {
                if m.optional {
                    return false;
                }
                let at_var = matches!(strip(&m.expression), Expression::Identifier(x) if x.name == sc.var.as_str());
                if let Some(name) = self.typed_array(&m.object) {
                    if at_var {
                        sc.typed.insert(name);
                        return true;
                    }
                    return self.scan_expr(&m.expression, sc, false);
                }
                let Expression::Identifier(object) = strip(&m.object) else {
                    return false;
                };
                let name = object.name.to_string();
                // J90-P3: `x[i + c]`, a constant offset past the loop variable.
                if let Some(c) = self.index_offset(&m.expression, &sc.var) {
                    let at = sc.offsets.entry(name.clone()).or_insert(0);
                    *at = (*at).max(c);
                    if !sink {
                        sc.numeric_arrays.insert(name.clone());
                    }
                    sc.plain.insert(name);
                    return true;
                }
                // J90-P3: `x[k]`, `k` a binding the body declares (a nested loop's variable): a
                // read the general lowering makes, of an array checked a list before the loop.
                let _ = at_var;
                match strip(&m.expression) {
                    Expression::Identifier(k) if sc.loop_vars.contains(k.name.as_str()) => {
                        sc.measured.insert(name);
                        self.scan_expr(&m.expression, sc, true)
                    }
                    _ => false,
                }
            }
            Expression::StaticMemberExpression(m) => {
                if m.optional || m.property.name != "length" {
                    return false;
                }
                if self.typed_array(&m.object).is_some() {
                    return true;
                }
                // J90-P: `.length` of a plain array named by a binding, checked a list before the
                // loop (`fast_copy`).
                let Expression::Identifier(object) = strip(&m.object) else {
                    return false;
                };
                sc.measured.insert(object.name.to_string());
                true
            }
            Expression::CallExpression(c) => self.scan_call(c, sc),
            _ => false,
        }
    }

    /// J87-3: `try { ... } catch (e?) { ... }`. Python's `except` sees every exception; only what a
    /// JS `catch` could see is caught (`_js_catch`: a JS Error, an adapter's OSError, the runtime's
    /// JS-worded TypeError), anything else (a subset refusal) propagates. The handler runs after
    /// the `try` statement, outside the `except`, so nothing it raises is chained to what was
    /// caught: a JS throw carries no implicit cause. `finally` is refused.
    fn try_stmt(&mut self, t: &TryStatement<'_>, indent: usize, out: &mut Vec<String>) {
        self.try_depth += 1;
        self.try_stmt_inner(t, indent, out);
        self.try_depth -= 1;
    }

    fn try_stmt_inner(&mut self, t: &TryStatement<'_>, indent: usize, out: &mut Vec<String>) {
        // J88-2: `finally` is Python's own: the try (and its catch) inside `try:`, the finalizer
        // under `finally:`. Both run it on a normal end, a return, a break and a throw, and a
        // `return` inside the finalizer replaces the completion in both.
        if let Some(finalizer) = &t.finalizer {
            let p = pad(indent);
            out.push(format!("{p}try:"));
            let start = out.len();
            if t.handler.is_some() {
                self.try_catch(t, indent + 1, out);
            } else {
                self.block(&t.block.body, indent + 1, out);
            }
            if out.len() == start {
                out.push(format!("{p}    pass"));
            }
            out.push(format!("{p}finally:"));
            let start = out.len();
            self.block(&finalizer.body, indent + 1, out);
            if out.len() == start {
                out.push(format!("{p}    pass"));
            }
            return;
        }
        self.try_catch(t, indent, out);
    }

    fn try_catch(&mut self, t: &TryStatement<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
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
            // J89-3: `const t = new Float64Array(n)`: a list of floats (SUBSET.md, *Typed arrays*).
            if let Some(Expression::NewExpression(n)) = d.init.as_ref().map(strip)
                && matches!(strip(&n.callee), Expression::Identifier(c) if c.name == "Float64Array")
                && !self.is_local("Float64Array")
            {
                if v.kind != VariableDeclarationKind::Const {
                    self.refuse(d.span, "a Float64Array bound by anything but a const");
                    continue;
                }
                let length = match n.arguments.as_slice() {
                    [arg] => match arg.as_expression() {
                        Some(e) => self.expr(e),
                        None => {
                            self.refuse(n.span, "new Float64Array of a spread");
                            continue;
                        }
                    },
                    _ => {
                        self.refuse(n.span, "argument count for new Float64Array");
                        continue;
                    }
                };
                if let Some(key) = self.var_key(id.name.as_str()) {
                    self.typed_arrays.insert(key);
                }
                self.bind_decl(id.name.as_str(), Fact::default());
                out.push(format!("{p}{name} = _js_f64_new({})", length.code));
                continue;
            }
            // J89-3: a `const` of an array literal or of `.slice(...)`'s answer holds an array (or,
            // from `.slice`, a string) that no parameter can alias.
            let fresh = match d.init.as_ref().map(strip) {
                Some(Expression::ArrayExpression(_)) => true,
                Some(Expression::CallExpression(c)) => {
                    matches!(strip(&c.callee), Expression::StaticMemberExpression(m) if m.property.name == "slice")
                }
                _ => false,
            };
            if fresh
                && v.kind == VariableDeclarationKind::Const
                && let Some(key) = self.var_key(id.name.as_str())
            {
                self.fresh_arrays.insert(key);
            }
            // J86: `const f = (...) => ...` inside a function is a nested `def` (a closure).
            if let (Some(Expression::ArrowFunctionExpression(a)), VariableDeclarationKind::Const) =
                (&d.init, v.kind)
            {
                // J91-3 (#341): the nested function's scope is `a.span.start` (`nested_def`).
                if let Some(key) = self.var_key(id.name.as_str()) {
                    self.observed.closures.insert(a.span.start, key);
                }
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
            // J91-3 (#341): a `const` bound to an `own` list, Map or Set, every read of which is a
            // sealed use (`Seal`), keeps what the value holds (`elem`): every change to it is a
            // `push` / `set` / `add` the compiler meets into the binding (`fill`).
            let sealed = v.kind == VariableDeclarationKind::Const
                && fact.own
                && !fact.top
                && self
                    .var_key(id.name.as_str())
                    .is_some_and(|key| !self.assume.unsealed.contains(&key));
            if held && let Some(key) = self.var_key(id.name.as_str()) {
                self.observed.declared.insert(key.clone());
                self.observed.observe(key, fact);
            } else if sealed && let Some(key) = self.var_key(id.name.as_str()) {
                self.observed.declared.insert(key.clone());
                self.observed.observe(key, sealed_fact(&fact));
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
                self.check_carried(id.name.as_str(), &value);
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
                self.check_carried(id.name.as_str(), &value);
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
            // J89-4a: `re.lastIndex = n` (a `g` regex's position): the subset models no
            // `lastIndex` (`.test` / `.exec` on a `g` regex raise at run time), so the write that
            // would set one is refused where it is written.
            AssignmentTarget::StaticMemberExpression(m) if m.property.name == "lastIndex" => {
                self.refuse(a.span, "assignment to lastIndex");
            }
            AssignmentTarget::StaticMemberExpression(m) => {
                if op.is_some() {
                    // J88-2: `o.k op= v` on a local object: read, combine, put back.
                    if !matches!(strip(&m.object), Expression::Identifier(id) if self.is_scoped(id.name.as_str()))
                    {
                        self.refuse(
                            a.span,
                            "compound assignment to a property of anything but a local",
                        );
                        return;
                    }
                    let object = self.expr(&m.object);
                    let key = py_str(m.property.name.as_str());
                    let current = Py::atom(format!("_js_get({}, {key})", object.code));
                    let value = self.assigned_value(op, current, &a.right);
                    out.push(format!(
                        "{p}_js_put({}, {key}, {})",
                        object.code, value.code
                    ));
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
            AssignmentTarget::ComputedMemberExpression(m)
                if self.typed_array(&m.object).is_some() =>
            {
                // J89-3: a Float64Array element stores ToNumber of the value, as a float, and only
                // at a valid index (`_js_ta_put`); in the proven copy of a counted loop, at the loop
                // variable, the store itself.
                let name = self.typed_array(&m.object).unwrap();
                let py = py_name(&name, false, false);
                if op.is_some() {
                    self.refuse(a.span, "compound assignment to a Float64Array element");
                    return;
                }
                if self.is_fast_index(&m.expression)
                    && self.fast.as_ref().is_some_and(|f| f.typed.contains(&name))
                {
                    let var = py_name(&self.fast.as_ref().unwrap().var, false, false);
                    let value = self.expr(&a.right);
                    if value.is_f64 && !value.top {
                        out.push(format!("{p}{py}[{var}] = {}", value.code));
                    } else if value.is_num && value.is_double && !value.top {
                        out.push(format!("{p}{py}[{var}] = float({})", value.code));
                    } else {
                        self.tmp += 1;
                        let t = format!("_js_t{}", self.tmp);
                        out.push(format!("{p}{t} = {}", value.code));
                        out.push(format!(
                            "{p}{py}[{var}] = {t} if type({t}) is float else _js_to_f64({t})"
                        ));
                    }
                    return;
                }
                let key = self.expr(&m.expression);
                let value = self.expr(&a.right);
                out.push(format!("{p}_js_ta_put({py}, {}, {})", key.code, value.code));
            }
            AssignmentTarget::ComputedMemberExpression(m) => {
                if op.is_some() {
                    // J88-2: `o[k] op= v` with a local object and a local or literal key.
                    let local = |e: &Expression<'_>, this: &Self| matches!(strip(e), Expression::Identifier(id) if this.is_scoped(id.name.as_str()));
                    let simple_key = local(&m.expression, self)
                        || matches!(
                            strip(&m.expression),
                            Expression::StringLiteral(_) | Expression::NumericLiteral(_)
                        );
                    if !local(&m.object, self) || !simple_key {
                        self.refuse(
                            a.span,
                            "compound assignment to a property of anything but a local",
                        );
                        return;
                    }
                    let object = self.expr(&m.object);
                    let key = self.expr(&m.expression);
                    let current = Py::atom(format!("_js_get({}, {})", object.code, key.code));
                    let value = self.assigned_value(op, current, &a.right);
                    out.push(format!(
                        "{p}_js_put({}, {}, {})",
                        object.code, key.code, value.code
                    ));
                    return;
                }
                // J89-3: in the proven copy of a counted loop, a fresh array its guard checked long
                // enough, at the loop variable: the store itself.
                if self.is_fast_index(&m.expression)
                    && let Expression::Identifier(id) = strip(&m.object)
                    && self
                        .fast
                        .as_ref()
                        .is_some_and(|f| f.filled.contains(id.name.as_str()))
                {
                    let py = py_name(id.name.as_str(), false, false);
                    let var = py_name(&self.fast.as_ref().unwrap().var, false, false);
                    let value = self.expr(&a.right);
                    out.push(format!("{p}{py}[{var}] = {}", value.code));
                    return;
                }
                let since = self.fact_seq;
                let object = self.expr(&m.object);
                let key = self.expr(&m.expression);
                let value = self.expr(&a.right);
                let code = format!("_js_put({}, {}, {})", object.code, key.code, value.code);
                match self.hot_stmt(&code, &p, since) {
                    Some(lines) => out.extend(lines),
                    None => out.push(format!("{p}{code}")),
                }
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
            None => {
                self.generator_call_ok = matches!(strip(&f.right), Expression::CallExpression(_));
                // J91-3 (#341): a for-of reads its iterable in place (`Seal::Use`).
                self.seal_next(&f.right, Seal::Use);
                let value = self.expr(&f.right);
                self.generator_call_ok = false;
                value
            }
        };
        // J87: what each element is: a string iterates by code point (each a `str`).
        let element = if right.top {
            Fact::top()
        } else if right.is_str {
            Fact::str_()
        } else {
            right.elem.as_deref().cloned().unwrap_or_default()
        };
        // J91-3 (#341): a for-of `const` is never reassigned in the body, so a guard may narrow
        // it there, as any `const` (`narrowable`); each pass binds it anew before the body runs.
        if v.kind == VariableDeclarationKind::Const {
            let mut names = Vec::new();
            match &v.declarations[0].id {
                BindingPattern::BindingIdentifier(id) => names.push(id.name.to_string()),
                BindingPattern::ArrayPattern(a) => {
                    for item in a.elements.iter().flatten() {
                        if let BindingPattern::BindingIdentifier(id) = item {
                            names.push(id.name.to_string());
                        }
                    }
                }
                _ => {}
            }
            for name in names {
                if let Some(key) = self.var_key(&name) {
                    self.consts.insert(key);
                }
            }
        }
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
                        // J89-4a: a hole (`[, p]`) binds nothing (each named element is read by
                        // its index, as before).
                        None => names.push("_js_hole".to_string()),
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
                } else if exact.is_some() && !right.is_map {
                    // J87: every element is a fresh array of exactly this many items. (J91-3: a
                    // Map's entries are, but `_js_rows` walks a Map without making them.)
                    out.push(format!("{p}for {} in {}:", names.join(", "), right.code));
                } else if right.is_list && !right.top {
                    // J91-2 (#341): a proven list, iterated by Python's own list iterator (as
                    // `_js_rows` iterates it), each item unpacked in the loop: a list of exactly
                    // the pattern's length is its items (what `_js_rows` yields for it), anything
                    // else is `_js_row`, `_js_rows`' answer for that one item. No generator.
                    let wanted: Vec<String> = names
                        .iter()
                        .enumerate()
                        .filter(|(_, name)| *name != "_js_hole")
                        .map(|(i, _)| i.to_string())
                        .collect();
                    self.hot_tmp += 1;
                    let item = format!("_js_r{}", self.hot_tmp);
                    out.push(format!("{p}for {item} in {}:", right.code));
                    out.push(format!(
                        "{p}    {}{} = {item} if type({item}) is list and len({item}) == {} else _js_row({item}, {}, ({}{}))",
                        names.join(", "),
                        if names.len() == 1 { "," } else { "" },
                        names.len(),
                        names.len(),
                        wanted.join(", "),
                        if wanted.len() == 1 { "," } else { "" }
                    ));
                } else {
                    // J90-P: each item through `_js_rows`, which slices a list long enough at
                    // once and reads anything else as the general lowering did (`_js_get` of
                    // each named index, in order).
                    let wanted: Vec<String> = names
                        .iter()
                        .enumerate()
                        .filter(|(_, name)| *name != "_js_hole")
                        .map(|(i, _)| i.to_string())
                        .collect();
                    out.push(format!(
                        "{p}for {}{} in _js_rows({}, {}, ({}{})):",
                        names.join(", "),
                        if names.len() == 1 { "," } else { "" },
                        right.code,
                        names.len(),
                        wanted.join(", "),
                        if wanted.len() == 1 { "," } else { "" }
                    ));
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
        let since = self.fact_seq;
        let value = self.expr_inner(e);
        self.hot(value, since)
    }

    /// J90-P6: guarded inline expansion of a hot helper call (RULES.md, *J90-P6 rules*). Inside a
    /// loop body, `_js_m_get(m, k)`, `_js_strict_eq(a, b)` and `_js_add(a, b)` are rewritten to a
    /// conditional expression whose fast arm is the helper's own first branch under an exact-type
    /// guard at least as strict, and whose slow arm is the unchanged helper call. Operands are
    /// evaluated once each, in their original order: every operand but the first must be a name
    /// or a literal (read again in the slow arm, with no code run in between); the first, if it is
    /// anything else, is bound by `:=` in the guard's first test, which always runs. Where `:=`
    /// cannot stand (a comprehension's iterable, a lambda), the first operand must be simple too.
    fn hot(&mut self, value: Py, since: u64) -> Py {
        // Measured (docs/porting.md, *Guarded inline expansion*): a comprehension element and the
        // other helpers (`_js_get`, `_js_num`, `_js_coalesce_value`, `_js_list_at`) moved no
        // path by more than the run's spread and cost the wheel 1.5x its size budget.
        if self.scopes.is_empty() || self.hot_comp > 0 || !self.breaks.contains(&BreakTarget::Loop)
        {
            return value;
        }
        let walrus = self.no_walrus == 0 && self.in_callback == 0;
        let (negate, call) = match value.code.strip_prefix("not ") {
            Some(rest) => (true, rest),
            None => (false, value.code.as_str()),
        };
        let Some((helper, args)) = split_call(call) else {
            return value;
        };
        let arity = match helper {
            "_js_m_get" | "_js_strict_eq" | "_js_add" => 2,
            // J90-PF: `m.has(k)`, a proven list read by an index, `xs.push(x)` of one item.
            "_js_m_has" | "_js_list_at" | "_js_m_push" => 2,
            _ => return value,
        };
        if args.len() != arity || (negate && helper != "_js_strict_eq") {
            return value;
        }
        if args[1..].iter().any(|a| !simple_operand(a)) {
            return value;
        }
        // A literal operand must be of the fast arm's own type (a literal of another type could
        // never take it), and the first is never a literal: the guard tests no literal's type.
        let literal = |a: &str| simple_operand(a) && !is_name(a);
        let second = &args[1];
        // J90-PF: an index literal is a non-negative int under 16 digits (its own type and range).
        let index_literal = |a: &str| is_int_literal(a) && !a.starts_with('-') && a.len() < 16;
        let literal_ok = match helper {
            "_js_m_get" | "_js_m_has" => {
                !literal(second) || is_str_literal(second) || index_literal(second)
            }
            "_js_strict_eq" => !literal(second),
            "_js_list_at" => !literal(second) || index_literal(second),
            "_js_m_push" => true,
            _ => {
                !literal(second)
                    || (is_int_literal(second) && second.trim_start_matches('-').len() < 16)
            }
        };
        let first = args[0].clone();
        if literal(&first) || !literal_ok {
            return value;
        }
        // J90-PF: `_js_list_at`'s guard tests no receiver, and `xs.append(x) or len(xs)` reads
        // the receiver again after the item: each must be a name.
        if matches!(helper, "_js_list_at" | "_js_m_push") && !is_name(&first) {
            return value;
        }
        // `type(t := x)`: an assignment expression may stand alone as a call's argument.
        let (bind, name) = if simple_operand(&first) {
            (first.clone(), first.clone())
        } else if walrus {
            self.hot_tmp += 1;
            let t = format!("_js_h{}", self.hot_tmp);
            (format!("{t} := {first}"), t)
        } else {
            return value;
        };
        // An addend the fast arm accepts lies within half the safe range (`_JS_SAFE_MAX / 2`), so
        // the exact sum of two is itself a double's exact int and `_js_num` would return it as is.
        const HALF: &str = "4503599627370496";
        // J90-PF: the ints a double holds exactly (`_JS_SAFE_MIN` / `_JS_SAFE_MAX`): each is its own
        // `_js_key` and compares by value under `===`.
        const SAFE: &str = "9007199254740992";
        let a = &name;
        // J91-1 (#341): what the operands' own reads proved (`proven`: names only, so never the
        // `:=`-bound first operand). A test the fact already answers is left out of the guard;
        // a guard with no test left is the fast arm alone.
        let fa = self.proven(&first, since);
        let fb = self.proven(&args[1], since);
        // A guard whose every test is proven: the fast arm. Else `(fast if <tests> else slow)`.
        let guarded = |fast: String, tests: Vec<String>, slow: String| -> String {
            if tests.is_empty() {
                format!("({fast})")
            } else {
                format!("({fast} if {} else {slow})", tests.join(" and "))
            }
        };
        let code = match helper {
            "_js_m_get" | "_js_m_has" => {
                let k = &args[1];
                // J90-PF: a key that is its own `_js_key`: a string, or a safe int (was: strings).
                // J91-1: or a key proven one (a `str`, a safe int).
                let key_test = if is_str_literal(k) || index_literal(k) || fb.str_ || fb.int_ {
                    None
                } else {
                    Some(format!(
                        "(type({k}) is str or type({k}) is int and -{SAFE} <= {k} <= {SAFE})"
                    ))
                };
                // J91-2 (#341): the receiver test stays even for a proven Map: it is what mypyc
                // narrows the receiver by, to read `_entries` from its struct (without it, a
                // generic attribute lookup); a proven Map only drops `has`'s Set arm.
                let map_test = Some(format!("type({bind}) is _JsMap"));
                let tests: Vec<String> = map_test.into_iter().chain(key_test.clone()).collect();
                if helper == "_js_m_get" {
                    guarded(
                        format!("{a}._entries.get({k}, _JS_UNDEFINED)"),
                        tests,
                        format!("_js_m_get({a}, {k})"),
                    )
                } else if fa.map {
                    // J91-1: a proven Map is never a Set, so its arm alone.
                    guarded(
                        format!("{k} in {a}._entries"),
                        tests,
                        format!("_js_m_has({a}, {k})"),
                    )
                } else {
                    // `has` of a Set too: its items are keyed by the same `_js_key` tags.
                    let key_test = key_test.map_or(String::new(), |t| format!(" and {t}"));
                    format!(
                        "({k} in {a}._entries if type({bind}) is _JsMap{key_test} else {k} in {a}._items if type({a}) is _JsSet{key_test} else _js_m_has({a}, {k}))"
                    )
                }
            }
            "_js_strict_eq" => {
                let b = &args[1];
                let (op, not) = if negate { ("!=", "not ") } else { ("==", "") };
                if fa.num || fb.num {
                    // J91-1: one side is a proven number, so the two are never two `str`s: only
                    // the int arm is left, less the tests a side proven a safe int answers.
                    let mut tests = Vec::new();
                    // J91-2 (#341): a side proven a safe int keeps `type(x) is int` (mypyc narrows
                    // it by that test) and drops only its range test.
                    for (x, f) in [(a, &fa), (b, &fb)] {
                        let x_bind = if x == a { &bind } else { x };
                        tests.push(format!("type({x_bind}) is int"));
                        if !f.int_ {
                            tests.push(format!("-{SAFE} <= {x} <= {SAFE}"));
                        }
                    }
                    // The `:=` binding of the first operand must stay the guard's first test.
                    if bind != *a && fa.int_ {
                        return value;
                    }
                    guarded(
                        format!("{a} {op} {b}"),
                        tests,
                        format!("{not}_js_strict_eq({a}, {b})"),
                    )
                } else {
                    // J90-PF: and two safe ints (the helper's second branch), compared by value.
                    format!(
                        "({a} {op} {b} if type({bind}) is type({b}) is str or type({a}) is type({b}) is int and -{SAFE} <= {a} <= {SAFE} and -{SAFE} <= {b} <= {SAFE} else {not}_js_strict_eq({a}, {b}))"
                    )
                }
            }
            "_js_list_at" => {
                // J90-PF: a proven list read at an int index inside it: the element (the helper's
                // own first branch). J91-1: less the tests an index proven an int (or an index)
                // answers.
                let i = &args[1];
                let i_test = if index_literal(i) {
                    format!("{i} < len({a})")
                } else if fb.idx {
                    // J91-2: `type(i) is int` stays, the test mypyc narrows `i` by.
                    format!("type({i}) is int and {i} < len({a})")
                } else {
                    // J91-2: a safe int that is not an index keeps every test (mypyc's narrowing).
                    format!("type({i}) is int and 0 <= {i} < len({a})")
                };
                format!("({a}[{i}] if {i_test} else _js_list_at({a}, {i}))")
            }
            "_js_m_push" => {
                // J90-PF: a list's push of one item is its append, and answers the new length
                // (the helper's own first branch). The item is a name or a literal, so reading the
                // receiver again for its length reads the same list.
                let x = &args[1];
                // J91-2 (#341): `type(a) is list` stays even for a proven list, the test mypyc
                // narrows the receiver by (to `PyList_Append`; without it, a generic method call).
                format!(
                    "({a}.append({x}) or len({a}) if type({a}) is list else _js_m_push({a}, {x}))"
                )
            }
            _ => {
                let b = &args[1];
                // J91-1: an index lies within half the safe range, so it needs no test either.
                // J91-2 (#341): an index keeps `type(b) is int` (mypyc's narrowing) and drops its
                // range test.
                let b_test = if is_int_literal(b) && b.trim_start_matches('-').len() < 16 {
                    String::new()
                } else if fb.idx {
                    format!(" and type({b}) is int")
                } else {
                    format!(" and type({b}) is int and -{HALF} <= {b} <= {HALF}")
                };
                if fa.idx && bind == *a {
                    let tests: Vec<String> = std::iter::once(format!("type({a}) is int"))
                        .chain(b_test.strip_prefix(" and ").map(|s| s.to_string()))
                        .collect();
                    guarded(format!("{a} + {b}"), tests, format!("_js_add({a}, {b})"))
                } else {
                    format!(
                        "({a} + {b} if type({bind}) is int{b_test} and -{HALF} <= {a} <= {HALF} else _js_add({a}, {b}))"
                    )
                }
            }
        };
        Py {
            code,
            prec: ATOM,
            ..value
        }
    }

    /// J90-P6 / J90-PF: where a guarded inline expansion may be written: a loop body of a
    /// function, outside a comprehension element.
    fn hot_here(&self) -> bool {
        !self.scopes.is_empty() && self.hot_comp == 0 && self.breaks.contains(&BreakTarget::Loop)
    }

    /// J90-PF: guarded inline expansion of a helper call that stands as a statement in a loop
    /// body of a function (RULES.md, *J90-PF rules*; where `hot` applies): `m.set(k, v)`,
    /// `xs.push(x)` and `xs[i] = v` are each written as an `if` whose first arm is the helper's
    /// own first branch under a guard at least as strict and whose `else` is the unchanged call.
    /// The receiver, key and value of `set` and of a store must each be a name or a literal (read
    /// again in the arm with no code run in between); a push's one item may be anything:
    /// `xs.append(x)` reads `xs` before it evaluates `x`, as JS reads the receiver first, and only
    /// one arm runs. The result is discarded, as the statement discards the call's.
    fn hot_stmt(&self, code: &str, p: &str, since: u64) -> Option<Vec<String>> {
        if !self.hot_here() {
            return None;
        }
        let (helper, args) = split_call(code)?;
        let name = |a: &str| is_name(a) && !matches!(a, "True" | "False" | "None");
        let index_literal = |a: &str| is_int_literal(a) && !a.starts_with('-') && a.len() < 16;
        const SAFE: &str = "9007199254740992";
        let q = format!("{p}    ");
        match (helper, args.as_slice()) {
            ("_js_m_set", [m, k, v]) if name(m) && simple_value(v) => {
                // J91-1 (#341): less the tests the receiver's and the key's facts answer (a
                // proven Map; a key proven a `str` or a safe int). `_keys is None` is a property of
                // the Map's contents, which a binding's fact does not prove, so it stays.
                let fk = self.proven(k, since);
                let key_test = if is_str_literal(k) || index_literal(k) {
                    String::new()
                } else if name(k) {
                    if fk.str_ || fk.int_ {
                        String::new()
                    } else {
                        format!(
                            "(type({k}) is str or type({k}) is int and -{SAFE} <= {k} <= {SAFE}) and "
                        )
                    }
                } else {
                    return None;
                };
                // J91-2 (#341): the receiver test stays for a proven Map, as for `get` (mypyc's
                // narrowing).
                let map_test = format!("type({m}) is _JsMap and ");
                Some(vec![
                    format!("{p}if {map_test}{key_test}{m}._keys is None:"),
                    format!("{q}{m}._entries[{k}] = {v}"),
                    format!("{p}else:"),
                    format!("{q}{code}"),
                ])
            }
            ("_js_m_push", [xs, _]) if name(xs) => {
                let item = &args[1];
                Some(vec![
                    format!("{p}if type({xs}) is list:"),
                    format!("{q}{xs}.append({item})"),
                    format!("{p}else:"),
                    format!("{q}{code}"),
                ])
            }
            ("_js_put", [xs, i, v]) if name(xs) && simple_operand(v) => {
                // J91-1 (#341): less the tests a receiver proven a list, and an index proven a
                // safe int (or an index), answer.
                let fi = self.proven(i, since);
                let i_test = if index_literal(i) {
                    format!("{i} < len({xs})")
                } else if name(i) && fi.idx {
                    // J91-2: `type(i) is int` stays, mypyc's narrowing.
                    format!("type({i}) is int and {i} < len({xs})")
                } else if name(i) {
                    // J91-2: a safe int that is not an index keeps every test (mypyc's narrowing).
                    format!("type({i}) is int and 0 <= {i} < len({xs})")
                } else {
                    return None;
                };
                // J91-2 (#341): the list test stays for a proven list (mypyc's narrowing).
                let list_test = format!("type({xs}) is list and ");
                Some(vec![
                    format!("{p}if {list_test}{i_test}:"),
                    format!("{q}{xs}[{i}] = {v}"),
                    format!("{p}else:"),
                    format!("{q}{code}"),
                ])
            }
            _ => None,
        }
    }

    fn expr_inner(&mut self, e: &Expression<'_>) -> Py {
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
                    // J89-3: a literal Python spells as a float (`0.75`, `-0.0`, `1e+21`).
                    let is_f64 = code.contains(['.', 'e']);
                    // J91-1 (#341): a whole literal Python spells as an int (`py_number`: below
                    // 2**53, not -0) is a safe int, and one in `[0, IDX_MAX]` an index.
                    let is_int = !is_f64 && code.bytes().all(|b| b.is_ascii_digit());
                    let is_idx = is_int && n.value <= crate::types::IDX_MAX as f64;
                    Py {
                        is_num: true,
                        is_double: true,
                        is_f64,
                        is_int,
                        is_idx,
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
                // J90-P: each branch under what the test being true (false) proves.
                let depth = self.narrow.len();
                self.narrow_on(&c.test, true);
                let yes = self.expr(&c.consequent);
                self.narrow.truncate(depth);
                self.narrow_on(&c.test, false);
                let no = self.expr(&c.alternate);
                self.narrow.truncate(depth);
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
                    return self.process_env_read(key, m.span);
                }
                // J90-3: a constant of a namespace-imported Node module (`path.sep`): its adapter
                // row, read by name. Anything else of the namespace stays refused below.
                if let Expression::Identifier(id) = strip(&m.object)
                    && !self.is_scoped(id.name.as_str())
                    && let Some(module) = self.namespaces.get(id.name.as_str()).cloned()
                    && let Some(adapter) =
                        self.ctx.adapters.import(&module, m.property.name.as_str())
                    && adapter.kind == AdapterKind::Constant
                {
                    self.imports
                        .entry(self.ctx.adapter_module.clone())
                        .or_default()
                        .insert(adapter.py_name.to_string());
                    return Py {
                        pure: true,
                        ..Py::atom(adapter.py_name.to_string())
                    };
                }
                // J89-3: a Float64Array's `.length` (fixed when it is made); nothing else of it.
                if let Some(name) = self.typed_array(&m.object) {
                    if m.property.name != "length" {
                        let construct = format!("a Float64Array's .{}", m.property.name);
                        return self.refuse(m.span, construct);
                    }
                    let py = py_name(&name, false, false);
                    return Py {
                        pure: true,
                        ..returned(Ret::Num, format!("len({py})"))
                    };
                }
                // J88-2: `process.env` itself as a value (a default parameter): a snapshot of the
                // environment taken where it is read (`process_env_all`), which a read-only use
                // cannot tell from the live object.
                if m.property.name == "env"
                    && matches!(strip(&m.object), Expression::Identifier(p) if p.name == "process")
                    && !self.is_local("process")
                {
                    let Some(adapter) = self.ctx.adapters.global("process.env.all") else {
                        return self.refuse(m.span, "process.env as a value: no declared adapter");
                    };
                    self.imports
                        .entry(self.ctx.adapter_module.clone())
                        .or_default()
                        .insert(adapter.py_name.to_string());
                    return Py::atom(format!("{}()", adapter.py_name));
                }
                // J88-2: `process.pid`, the adapter.
                if let Expression::Identifier(id) = strip(&m.object)
                    && id.name == "process"
                    && m.property.name == "pid"
                    && !self.is_local("process")
                {
                    let Some(adapter) = self.ctx.adapters.global("process.pid") else {
                        return self.refuse(m.span, "process.pid: no declared adapter");
                    };
                    self.imports
                        .entry(self.ctx.adapter_module.clone())
                        .or_default()
                        .insert(adapter.py_name.to_string());
                    return returned(Ret::Num, format!("{}()", adapter.py_name));
                }
                // J88-2: `x.constructor`, as an object whose `name` is the constructor's name
                // (`_js_constructor_of`); the function itself is never handed out.
                if m.property.name == "constructor"
                    && !matches!(strip(&m.object), Expression::ThisExpression(_))
                {
                    let object = self.expr(&m.object);
                    return Py::atom(format!("_js_constructor_of({})", object.code));
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
                // J91-3 (#341): `.length` / `.size` of a local reads it without letting it escape.
                if matches!(m.property.name.as_str(), "length" | "size") {
                    self.seal_next(&m.object, Seal::Use);
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
                        Some(units) => len_idx(returned(Ret::Num, format!("len({units})"))),
                        None => {
                            len_idx(returned(Ret::Num, format!("_js_str_len({})", object.code)))
                        }
                    },
                    "length" if object.is_list => {
                        len_idx(returned(Ret::Num, format!("len({})", object.code)))
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
                    return self.process_env_read(key.code, m.span);
                }
                // J89-3: an element of a Float64Array: a float, or `undefined` for a key that is
                // not a valid index (`_js_ta_get`); in the proven copy of a counted loop, at the
                // loop variable, the element itself.
                if let Some(name) = self.typed_array(&m.object) {
                    let py = py_name(&name, false, false);
                    if self.is_fast_index(&m.expression)
                        && self.fast.as_ref().is_some_and(|f| f.typed.contains(&name))
                    {
                        let var = py_name(&self.fast.as_ref().unwrap().var, false, false);
                        return Py {
                            pure: true,
                            ..Py::atom(format!("{py}[{var}]")).with_fact(Some(&Fact::f64()))
                        };
                    }
                    let key = self.expr(&m.expression);
                    return Py::atom(format!("_js_ta_get({py}, {})", key.code))
                        .with_fact(Some(&Fact::or_undefined(Fact::f64())));
                }
                // J89-3: in the proven copy of a counted loop, an element of a plain array its guard
                // checked (`_js_doubles`): a proven number. J90-P3: at `i + c` too, and an element
                // of an array the guard only bounds-checked, read as it is (proving nothing).
                if let Some(c) = self.fast_offset(&m.expression)
                    && let Expression::Identifier(id) = strip(&m.object)
                    && let Some(fast) = self.fast.as_ref()
                    && (fast.plain.contains(id.name.as_str())
                        || fast.pass.contains(id.name.as_str()))
                {
                    let fact = if fast.plain.contains(id.name.as_str()) {
                        Fact::num()
                    } else {
                        Fact::default()
                    };
                    let py = py_name(id.name.as_str(), false, false);
                    let var = py_name(&fast.var, false, false);
                    let at = if c == 0 { var } else { format!("{var} + {c}") };
                    return Py {
                        pure: true,
                        ..Py::atom(format!("{py}[{at}]")).with_fact(Some(&fact))
                    };
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
                // J90-PF: inside a loop body, a read by a key proven a number, of a receiver and a
                // key that are names: the list's element when the receiver is a list and the key
                // an int index inside it (`_js_get`'s own branch for that pair), else `_js_get`.
                let index_literal =
                    literal_index.is_some() && is_int_literal(&key.code) && key.code.len() < 16;
                let read = if key.is_num
                    && self.hot_here()
                    && is_name(&object.code)
                    && (is_name(&key.code) || index_literal)
                {
                    let (o, k) = (&object.code, &key.code);
                    // J91-1 (#341): less the tests a key proven a safe int (or an index) answers.
                    // J91-2: an index keeps `type(k) is int`, the test mypyc narrows `k` by (no
                    // test is left for a literal, which mypyc already types an int).
                    let k_test = if index_literal {
                        format!("{k} < len({o})")
                    } else if key.is_idx && !key.top {
                        format!("type({k}) is int and {k} < len({o})")
                    } else {
                        // J91-2: a safe int that is not an index keeps every test (its sign
                        // test, and `type(k) is int` for mypyc).
                        format!("type({k}) is int and 0 <= {k} < len({o})")
                    };
                    Py::atom(format!(
                        "({o}[{k}] if type({o}) is list and {k_test} else _js_get({o}, {k}))"
                    ))
                } else {
                    Py::atom(format!("_js_get({}, {})", object.code, key.code))
                };
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
            // J88-2: an arrow used as a value (passed to a function, say) is a nested `def` emitted
            // before the statement, which closes over the enclosing locals as the arrow does;
            // refused inside a callback lambda (whose parameters the `def` could not see) and,
            // by `nested_def`, inside a loop.
            Expression::ArrowFunctionExpression(a) => self.hoisted_arrow(a),
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
    fn process_env_read(&mut self, key: String, span: Span) -> Py {
        let Some(adapter) = self.ctx.adapters.global("process.env") else {
            return self.refuse(span, "process.env read: no declared adapter");
        };
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
                    self.generator_call_ok =
                        matches!(strip(&s.argument), Expression::CallExpression(_));
                    let value = self.expr(&s.argument);
                    self.generator_call_ok = false;
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
        // J91-3 (#341): no element at all is vacuously anything (`Fact::top`, the identity of a
        // meet), so `[]` met with an `own` list keeps that list's `elem`.
        let elem = tuple.as_ref().map(|facts| {
            let mut all = facts.iter();
            Box::new(match all.next() {
                Some(first) => all.fold(first.clone(), |acc, f| acc.meet(f)),
                None => Fact::top(),
            })
        });
        Py {
            pure: items.is_empty(),
            is_list: true,
            // J91-3: a list just made: nothing else holds it.
            own: true,
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
            // J88-2: `a << b`, folded when both are small non-negative integer literals.
            Op::ShiftLeft => {
                if let (Expression::NumericLiteral(l), Expression::NumericLiteral(r)) =
                    (strip(&b.left), strip(&b.right))
                    && l.value >= 0.0
                    && l.value.fract() == 0.0
                    && r.value >= 0.0
                    && r.value.fract() == 0.0
                    && r.value < 31.0
                    && l.value < 2f64.powi(31 - r.value as i32)
                {
                    let folded = (l.value as i64) << (r.value as i64);
                    return Py {
                        is_num: true,
                        is_double: true,
                        pure: true,
                        ..Py::atom(folded.to_string())
                    };
                }
                let left = self.expr(&b.left);
                let right = self.expr(&b.right);
                returned(Ret::Num, format!("_js_shl({}, {})", left.code, right.code))
            }
            // J89-4a: `a >> b`, the sign-propagating shift (`_js_sar`: ToInt32 of the left, the
            // count mod 32; a Python `>>` of an int in Int32 range is the same arithmetic shift).
            Op::ShiftRight => {
                let left = self.expr(&b.left);
                let right = self.expr(&b.right);
                returned(Ret::Num, format!("_js_sar({}, {})", left.code, right.code))
            }
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
                        // J90-P7: through `_js_instanceof`, which mypyc compiles as the builtin.
                        Py::boolean(format!("_js_instanceof({}, {class})", value.code), ATOM)
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
        // J90-P: `typeof x === 'string'` (or 'number', 'boolean', 'undefined', either side, or
        // `!==`): the one type test `_js_typeof` answers that name for, without the name.
        for (side, other) in [(left, right), (right, left)] {
            if let (Expression::UnaryExpression(u), Expression::StringLiteral(name)) =
                (strip_parens(side), strip_parens(other))
                && u.operator == UnaryOperator::Typeof
            {
                let test = match name.value.as_str() {
                    Some("string") => Some("isinstance({}, str)"),
                    Some("boolean") => Some("isinstance({}, bool)"),
                    Some("number") => Some("_js_is_number({})"),
                    Some("undefined") => Some("{} is _JS_UNDEFINED"),
                    _ => None,
                };
                if let Some(test) = test {
                    let value = self.expr(&u.argument);
                    let operand = if test.starts_with('{') {
                        value.at(CMP + 1)
                    } else {
                        value.code.clone()
                    };
                    if negate && test == "{} is _JS_UNDEFINED" {
                        return Py::boolean(format!("{operand} is not _JS_UNDEFINED"), CMP);
                    }
                    let code = test.replace("{}", &operand);
                    return if negate {
                        Py::boolean(format!("not {code}"), NOT)
                    } else if test.starts_with('{') {
                        Py::boolean(code, CMP)
                    } else {
                        Py::boolean(code, ATOM)
                    };
                }
            }
        }
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
        // J90-P: the right side runs only where the left is truthy (`&&`) or falsy (`||`), so it
        // is lowered under what that proves of `const` bindings, as an `if` narrows its branches.
        let depth = self.narrow.len();
        let length_ok = self.length_ok;
        match l.operator {
            LogicalOperator::And => {
                self.length_ok = self.pure_test(&l.right);
                self.narrow_on(&l.left, true);
            }
            LogicalOperator::Or => {
                self.length_ok = false;
                self.narrow_on(&l.left, false);
            }
            LogicalOperator::Coalesce => self.length_ok = false,
        }
        let right = self.expr(&l.right);
        self.length_ok = length_ok;
        self.narrow.truncate(depth);
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
                // The value is one of the two operands (J87: so is what it proves). J91-3
                // (#341): `a ?? b` is `a` only where `a` is neither `null` nor `undefined`, so
                // what `a` is when defined, met with `b`.
                let both = if op == LogicalOperator::Coalesce && !left.top {
                    let defined = left.fact().defined().unwrap_or_default();
                    Py::atom("")
                        .with_fact(Some(&defined))
                        .meet_into(&right, Py::atom(code))
                } else {
                    left.meet_into(&right, Py::atom(code))
                };
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
                // J91-1: the negation of a non-zero int literal below 2**53 is a safe int.
                let is_int = value.is_int;
                Py {
                    is_num: true,
                    is_double: true,
                    is_int,
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
        let spread_list = std::mem::take(&mut self.spread_list);
        let mut out = Vec::new();
        for (i, arg) in args.iter().enumerate() {
            let Some(e) = arg.as_expression() else {
                if let Argument::SpreadElement(spread) = arg
                    && spread_ok
                {
                    // J86: `a.push(...xs)` spreads any iterable, as a Python `*xs` does.
                    let value = self.expr(&spread.argument);
                    if spread_list && !value.is_list {
                        self.refuse(spread.span, "spread of a value not proven an array");
                        return None;
                    }
                    out.push(Py::atom(format!("*{}", value.at(ATOM))));
                    continue;
                }
                self.refuse(arg.span(), "spread argument");
                return None;
            };
            if callback == Some(i) {
                match strip(e) {
                    Expression::ArrowFunctionExpression(a) => out.push(self.callback(a)),
                    // J88-2: a module function by name (`rows.map(dumpsLine)`): called with as
                    // many of the callback's arguments as it declares parameters, as JS binds
                    // them (the rest JS passes are ignored by a function that declares none).
                    Expression::Identifier(id)
                        if !self.is_scoped(id.name.as_str())
                            && self.sigs.contains_key(id.name.as_str())
                            && !self.generator_fns.contains(id.name.as_str()) =>
                    {
                        let n = self.sigs[id.name.as_str()].params.len();
                        let callee = self.resolve(id.name.as_str(), id.span);
                        let args: Vec<String> =
                            (0..n).map(|k| format!("_js_a{k}=_JS_UNDEFINED")).collect();
                        let pass: Vec<String> = (0..n).map(|k| format!("_js_a{k}")).collect();
                        let mut params = args;
                        params.push("*_".to_string());
                        out.push(Py::new(
                            format!(
                                "lambda {}: {}({})",
                                params.join(", "),
                                callee.code,
                                pass.join(", ")
                            ),
                            LAMBDA,
                        ));
                    }
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
            // J88-2: a block body is a loose nested `def` before the statement (`hoisted_arrow`).
            ArrowFunctionBody::FunctionBody(b) => {
                if self.in_callback > 0 || self.scopes.is_empty() {
                    return self.refuse(b.span, "block-bodied arrow function in a callback");
                }
                return self.hoisted_arrow(a);
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
            // J90-P: an expression body cannot assign a parameter (an assignment inside an
            // expression is refused), so each is a `const` there, which a guard may narrow.
            if let Some(key) = self.var_key(&name) {
                self.consts.insert(key);
            }
        }
        // J89-5: an annotated parameter declares its data fields (`(o: Omission) => o.count`), as
        // a function's parameter does (`bind_params`).
        for p in &a.params.items {
            if let BindingPattern::BindingIdentifier(id) = &p.pattern {
                self.declare_annotation(id.name.as_str(), p.type_annotation.as_deref());
            }
        }
        self.rets.push(None);
        self.in_callback += 1;
        let value = self.expr(body);
        self.in_callback -= 1;
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

    /// J90-P2: an expression that cannot change any array's length or run code that could: names,
    /// literals, member reads (a getter is assumed to have no effect, as the key sorts assume),
    /// `typeof`, `!`, `-`, comparisons, arithmetic, `&&` / `||` / `??`, `?:`, and calls of
    /// `Number.isInteger`, `Number.isNaN` and `Array.isArray` on such expressions.
    fn pure_test(&self, e: &Expression<'_>) -> bool {
        match strip(e) {
            Expression::Identifier(_)
            | Expression::NumericLiteral(_)
            | Expression::StringLiteral(_)
            | Expression::BooleanLiteral(_)
            | Expression::NullLiteral(_) => true,
            Expression::StaticMemberExpression(m) => self.pure_test(&m.object),
            Expression::ComputedMemberExpression(m) => {
                self.pure_test(&m.object) && self.pure_test(&m.expression)
            }
            Expression::UnaryExpression(u) => {
                matches!(
                    u.operator,
                    UnaryOperator::Typeof
                        | UnaryOperator::LogicalNot
                        | UnaryOperator::UnaryNegation
                ) && self.pure_test(&u.argument)
            }
            Expression::BinaryExpression(b) => {
                !matches!(b.operator, BinaryOperator::In | BinaryOperator::Instanceof)
                    && self.pure_test(&b.left)
                    && self.pure_test(&b.right)
            }
            Expression::LogicalExpression(l) => self.pure_test(&l.left) && self.pure_test(&l.right),
            Expression::ConditionalExpression(c) => {
                self.pure_test(&c.test)
                    && self.pure_test(&c.consequent)
                    && self.pure_test(&c.alternate)
            }
            Expression::CallExpression(c) => {
                let known = matches!(strip(&c.callee), Expression::StaticMemberExpression(m)
                    if !m.optional
                        && matches!(strip(&m.object), Expression::Identifier(o)
                            if (o.name == "Number" && matches!(m.property.name.as_str(), "isInteger" | "isNaN"))
                                || (o.name == "Array" && m.property.name == "isArray")));
                known
                    && !self.is_local("Number")
                    && !self.is_local("Array")
                    && !c.optional
                    && c.arguments
                        .iter()
                        .all(|a| a.as_expression().is_some_and(|e| self.pure_test(e)))
            }
            _ => false,
        }
    }

    /// J90-P2: an arrow `(x) => e` whose body a comprehension may hold in place of the lambda
    /// `callback` makes: one plain parameter (no default, no pattern, no rest), an expression body,
    /// and no function in `e` (one could outlive its element, and a comprehension's variable is
    /// one binding for every element, a lambda's parameter one per call).
    fn inlinable_callback(&self, a: &ArrowFunctionExpression<'_>) -> bool {
        let Some(body) = a.body.as_expression() else {
            return false;
        };
        let text = self.text(body.span());
        !a.r#async
            && a.params.rest.is_none()
            && a.params.items.len() == 1
            && a.params.items[0].initializer.is_none()
            && matches!(
                a.params.items[0].pattern,
                BindingPattern::BindingIdentifier(_)
            )
            && !text.contains("=>")
            && !text.contains("function")
            && !text.contains("class")
    }

    /// J90-P2: the parameter's Python name and the body of an `inlinable_callback`, lowered as
    /// `callback` lowers it (the parameter a `const` a guard may narrow).
    fn inline_callback(&mut self, a: &ArrowFunctionExpression<'_>) -> (String, Py) {
        let BindingPattern::BindingIdentifier(id) = &a.params.items[0].pattern else {
            unreachable!("inlinable_callback checked a plain parameter")
        };
        let body = a
            .body
            .as_expression()
            .expect("inlinable_callback checked an expression body");
        let py = py_name(id.name.as_str(), false, false);
        self.claim(id.name.as_str(), &py, id.span);
        let mut scope = HashSet::new();
        scope.insert(id.name.to_string());
        self.push_scope(scope, a.span.start);
        self.bind(id.name.as_str(), Fact::default());
        if let Some(key) = self.var_key(id.name.as_str()) {
            self.consts.insert(key);
        }
        self.declare_annotation(
            id.name.as_str(),
            a.params.items[0].type_annotation.as_deref(),
        );
        self.rets.push(None);
        self.in_callback += 1;
        let value = self.expr(body);
        self.in_callback -= 1;
        self.rets.pop();
        self.pop_scope();
        (py, value)
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
                if as_statement {
                    // J90-PF: several items: `_js_m_push`'s own `extend` of them, in order (the
                    // receiver is read first, then each item, as JS reads them).
                    let items: Vec<String> = args.iter().map(|a| a.code.clone()).collect();
                    return Some(Py::atom(format!(
                        "{}.extend(({},))",
                        receiver.at(ATOM),
                        items.join(", ")
                    )));
                }
                // J91-1: a list's push answers its new length, an index (`len_idx`).
                Some(len_idx(returned(
                    Ret::Num,
                    format!("_js_m_push({})", all(args)),
                )))
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
            // J90-PF: `s.endsWith(lit)` / `s.startsWith(lit)`, `lit` an ASCII string literal and
            // the one argument: Python's own `endswith` / `startswith` on a `str` (an ASCII unit
            // is its own code point, and no surrogate unit equals one, so comparing the last or
            // first code units is comparing those code points), else the helper. A receiver that
            // is not a proven `str` must be a name, read twice.
            "endsWith" | "startsWith"
                if args.len() == 1
                    && matches!(call.arguments.first().and_then(|a| a.as_expression()).map(strip),
                        Some(Expression::StringLiteral(l)) if l.value.as_str().is_some_and(str::is_ascii))
                    && (receiver.is_str || is_name(&receiver.code)) =>
            {
                let py = if method == "endsWith" {
                    "endswith"
                } else {
                    "startswith"
                };
                let lit = &args[0].code;
                if receiver.is_str {
                    Some(Py::boolean(
                        format!("{}.{py}({lit})", receiver.at(ATOM)),
                        ATOM,
                    ))
                } else {
                    let r = &receiver.code;
                    Some(Py::boolean(
                        format!(
                            "({r}.{py}({lit}) if type({r}) is str else _js_m_{method}({r}, {lit}))"
                        ),
                        ATOM,
                    ))
                }
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
        let generator_ok = std::mem::take(&mut self.generator_call_ok);
        if c.optional {
            return self.refuse(c.span, "optional call");
        }
        match strip(&c.callee) {
            Expression::Identifier(id) => {
                let name = id.name.as_str();
                // J89-4a: a generator's object is iterated where it is made, so it is never held
                // (a JS `break` closes it; a Python one leaves it open to be iterated again).
                if !generator_ok && !self.is_scoped(name) && self.generator_fns.contains(name) {
                    return self.refuse(
                        c.span,
                        "generator function called anywhere but as a for-of's iterable or an array spread",
                    );
                }
                // J91-2 (#341): `parseInt(<hash chain>.slice(0, N), 16)`, the hash chain J90-P2's
                // (`createHash(alg).update(x, 'utf8').digest('hex')`) and N a whole literal in
                // `[1, 13]`: `hash_hex_int(alg, x, N)`, the int of the digest's first N hex digits
                // (below 16**13 = 2**52, an index). `x` is evaluated first and nothing else can
                // throw before the hash reads it, as in JS.
                if name == "parseInt"
                    && !self.is_local(name)
                    && let Some((alg, data, digits)) = self.hash_int_chain(c)
                {
                    self.imports
                        .entry(self.ctx.adapter_module.clone())
                        .or_default()
                        .insert("hash_hex_int".to_string());
                    let value = self.expr(data);
                    return len_idx(returned(
                        Ret::Num,
                        format!("hash_hex_int({}, {}, {digits})", py_str(alg), value.code),
                    ));
                }
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
                // J91-3 (#341): a direct call of a local function (`Seal::Call`).
                if self.is_scoped(name) {
                    self.seal = Some(Seal::Call);
                }
                let callee = self.resolve(name, id.span);
                // J88-2: an adapter function called with `...xs` of an array PROVEN a list.
                if self.adapter_fns.contains(name)
                    && !self.is_scoped(name)
                    && c.arguments
                        .iter()
                        .any(|a| matches!(a, Argument::SpreadElement(_)))
                {
                    let mut codes = Vec::new();
                    for arg in &c.arguments {
                        match arg {
                            Argument::SpreadElement(spread) => {
                                let value = self.expr(&spread.argument);
                                if !value.is_list {
                                    return self.refuse(
                                        spread.span,
                                        "spread of a value not proven an array",
                                    );
                                }
                                codes.push(format!("*{}", value.at(ATOM)));
                            }
                            other => {
                                let e = other.as_expression().expect("not a spread");
                                codes.push(self.expr(e).code);
                            }
                        }
                    }
                    return Py::atom(format!("{}({})", callee.code, codes.join(", ")));
                }
                let Some(lowered) = self.args_py(&c.arguments, None, false) else {
                    return Py::atom("None");
                };
                let args: Vec<String> = lowered.iter().map(|a| a.code.clone()).collect();
                let called = Py::atom(format!("{}({})", callee.code, args.join(", ")));
                // J91-3 (#341): an adapter whose row promises a `str` (`Contract::Str`): its answer.
                if self.str_fns.contains(name) && !self.is_scoped(name) {
                    return Py {
                        is_str: true,
                        ..called
                    };
                }
                // J91-3 (#341): a function of another compiled module proves of its answer what
                // its returns proved there (`ModuleExports::rets`).
                match self
                    .imported_rets
                    .get(name)
                    .filter(|_| !self.is_scoped(name))
                {
                    Some(fact) => {
                        let fact = fact.clone();
                        called.with_fact(Some(&fact))
                    }
                    None => called,
                }
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
                    // J88-2: `this.f(...)` where `f` is a FIELD holding a function (a clock the
                    // constructor was given): the attribute called. JS passes `this` and Python
                    // does not, which only a function reading `this` could see; such a function
                    // is a method or a class, never a field value ts2py compiles.
                    let field = self
                        .class_ctx
                        .as_ref()
                        .is_some_and(|class| class.members.contains(method));
                    if !declared && field {
                        let Some(args) = self.args(&c.arguments, None, false) else {
                            return Py::atom("None");
                        };
                        return Py::atom(format!("self.{method}({})", args.join(", ")));
                    }
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
                // J88-2: `new Date(ms).toISOString()`.
                if method == "toISOString"
                    && c.arguments.is_empty()
                    && let Expression::NewExpression(n) = strip(&m.object)
                    && matches!(strip(&n.callee), Expression::Identifier(d) if d.name == "Date")
                    && !self.is_local("Date")
                    && n.arguments.is_empty()
                {
                    // J89-4a: `new Date().toISOString()` is the clock now: `new Date(Date.now())`.
                    return returned(Ret::Str, "_js_date_to_iso(_js_now())".to_string());
                }
                if method == "toISOString"
                    && c.arguments.is_empty()
                    && let Expression::NewExpression(n) = strip(&m.object)
                    && matches!(strip(&n.callee), Expression::Identifier(d) if d.name == "Date")
                    && !self.is_local("Date")
                    && n.arguments.len() == 1
                {
                    let Some(args) = self.args(&n.arguments, None, false) else {
                        return Py::atom("None");
                    };
                    return returned(Ret::Str, format!("_js_date_to_iso({})", args[0]));
                }
                // J90-P2: `createHash('sha256' | 'sha1').update(x, 'utf8').digest('hex')` (the
                // node:crypto adapter): `hash_hex(alg, x)`, the three calls' checks and bytes at
                // once. The algorithm is a literal the adapter takes, so no call can throw before
                // `x` is evaluated, as in JS.
                if method == "digest"
                    && let Some((alg, data)) = self.hash_chain(c, m)
                {
                    self.imports
                        .entry(self.ctx.adapter_module.clone())
                        .or_default()
                        .insert("hash_hex".to_string());
                    let value = self.expr(data);
                    return returned(
                        Ret::Str,
                        format!("hash_hex({}, {})", py_str(alg), value.code),
                    );
                }
                if let Expression::Identifier(object) = strip(&m.object)
                    && !self.is_local(object.name.as_str())
                    && !self.classes.contains_key(object.name.as_str())
                {
                    return self.static_call(object.name.as_str(), method, c);
                }
                // J88-2: `C.m(...)`, a static method a compiled class declares.
                if let Expression::Identifier(object) = strip(&m.object)
                    && !self.is_scoped(object.name.as_str())
                    && let Some(py) = self.classes.get(object.name.as_str()).cloned()
                {
                    let Some(args) = self.args(&c.arguments, None, false) else {
                        return Py::atom("None");
                    };
                    return Py::atom(format!("{py}.{method}({})", args.join(", ")));
                }
                let builtin = METHODS.iter().find(|(name, ..)| *name == method);
                let class_method = self.ctx.class_methods.contains(method)
                    || self.imported_methods.contains(method);
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
                // J89-3: `xs.sort((a, b) => t[b] - t[a] || a - b)` (or `t[a] - t[b]`) for `t` a
                // Float64Array: a key sort when the items allow it (`_js_sort_by_f64`), else the
                // general sort with the same comparator.
                let by_key = if method == "sort" && c.arguments.len() == 1 {
                    c.arguments[0]
                        .as_expression()
                        .and_then(|e| self.key_comparator(e))
                } else {
                    None
                };
                // J90-P: `xs.sort((a, b) => k(a) - k(b))` (or `k(b) - k(a)`) for a pure key `k`:
                // a stable sort by the keys when every key is a number and none is NaN
                // (`_js_sort_keyed`), else the general sort with the same comparator.
                let keyed = if method == "sort"
                    && !class_method
                    && by_key.is_none()
                    && c.arguments.len() == 1
                {
                    c.arguments[0]
                        .as_expression()
                        .and_then(|e| self.keyed_comparator(e))
                } else {
                    None
                };
                // J90-P2: `xs.sort((a, b) => k1(a) - k1(b) || cmpCodepoint(k2(a), k2(b)) || ...)`:
                // stable sorts by each key, last first, when every key is a number JS holds
                // exactly and none is NaN (a code-point key: a `str`), else the general sort.
                let lex = if method == "sort"
                    && !class_method
                    && by_key.is_none()
                    && keyed.is_none()
                    && c.arguments.len() == 1
                {
                    c.arguments[0]
                        .as_expression()
                        .and_then(|e| self.lex_comparator(e))
                } else {
                    None
                };
                // J90-2: `xs.every((x) => Number.isInteger(x))` / `xs.every((x) => typeof x ===
                // 'string')`, the hot index's shape checks over 5,000-element columns: one helper
                // per test, which answers at C speed for a list of exactly that Python type and
                // runs the same per-element test as the general lowering otherwise.
                if method == "every"
                    && !class_method
                    && c.arguments.len() == 1
                    && let Some(test) = c.arguments[0]
                        .as_expression()
                        .and_then(|e| self.every_test(e))
                {
                    let receiver = self.expr(&m.object);
                    let result =
                        returned(Ret::Bool, format!("_js_every_{test}({})", receiver.code));
                    return if receiver.top {
                        result.with_fact(None)
                    } else {
                        result
                    };
                }
                // J90-P2: `xs.every/some/map/filter((x) => e)` with one plain parameter and no
                // function inside `e`: the comprehension `_js_m_every` (...) runs, with `e` inline
                // instead of a lambda called per element.
                if matches!(method, "every" | "some" | "map" | "filter")
                    && !class_method
                    && c.arguments.len() == 1
                    && let Some(Expression::ArrowFunctionExpression(arrow)) =
                        c.arguments[0].as_expression().map(strip)
                    && self.inlinable_callback(arrow)
                {
                    // J90-P6: the comprehension's iterable, where `:=` is a SyntaxError.
                    self.no_walrus += 1;
                    let receiver = self.expr(&m.object);
                    self.no_walrus -= 1;
                    let items = if receiver.is_list {
                        receiver.at(OR + 1)
                    } else {
                        format!("_js_array({}, {})", py_str(method), receiver.code)
                    };
                    self.hot_comp += 1;
                    let (param, value) = self.inline_callback(arrow);
                    self.hot_comp -= 1;
                    // A comprehension's element may be a conditional expression; its `if` clause
                    // may not.
                    let test = |v: &Py, prec: u8| {
                        if v.is_bool {
                            v.at(prec)
                        } else {
                            format!("_js_truthy({})", v.code)
                        }
                    };
                    let (code, ret) = match method {
                        "every" => (
                            format!("all({} for {param} in {items})", test(&value, TERNARY)),
                            Ret::Bool,
                        ),
                        "some" => (
                            format!("any({} for {param} in {items})", test(&value, TERNARY)),
                            Ret::Bool,
                        ),
                        "map" => (
                            format!("[{} for {param} in {items}]", value.at(TERNARY)),
                            Ret::List,
                        ),
                        _ => (
                            format!("[{param} for {param} in {items} if {}]", test(&value, OR)),
                            Ret::List,
                        ),
                    };
                    let result = returned(ret, code);
                    return if receiver.top || value.top {
                        result.with_fact(None)
                    } else {
                        result
                    };
                }
                // J91-3 (#341): these read or change the receiver in place (`Seal::Use`).
                if matches!(method, "push" | "set" | "get" | "has" | "add") {
                    self.seal_next(&m.object, Seal::Use);
                }
                let receiver = self.expr(&m.object);
                // J89-4a: `a.splice(start, count, ...xs)`, `xs` proven a list.
                let splice_spread = method == "splice";
                self.spread_list = splice_spread;
                let lowered =
                    self.args_py(&c.arguments, callback, method == "push" || splice_spread);
                let Some(args) = lowered else {
                    return Py::atom("None");
                };
                let spread = c
                    .arguments
                    .iter()
                    .any(|a| matches!(a, Argument::SpreadElement(_)));
                // J91-3 (#341): what a `push` / `set` / `add` puts into a local `const` (`fill`).
                if let Some(fact) = fill_fact(method, &args, spread) {
                    self.fill(&m.object, fact);
                }
                if let Some((keys, descending)) = by_key {
                    let code = format!(
                        "_js_sort_by_f64({}, {}, {}, {})",
                        receiver.code,
                        py_name(&keys, false, false),
                        if descending { "True" } else { "False" },
                        args[0].code
                    );
                    let result = returned(Ret::List, code);
                    return if receiver.top {
                        result.with_fact(None)
                    } else {
                        result
                    };
                }
                if let Some((arrow, key, descending)) = keyed {
                    // J90-PF: `(a, b) => a - b` (or `b - a`): the item is its own key, so a list
                    // of safe ints sorts by value (`_js_sort_num`), else `_js_sort_keyed` as before.
                    let identity = matches!(
                        (strip(key), &arrow.params.items[0].pattern),
                        (Expression::Identifier(k), BindingPattern::BindingIdentifier(p))
                            if k.name == p.name
                    );
                    let flag = if descending { "True" } else { "False" };
                    let code = if identity {
                        format!(
                            "_js_sort_num({}, {}, {})",
                            receiver.code, flag, args[0].code
                        )
                    } else {
                        let key = self.key_lambda(arrow, key);
                        format!(
                            "_js_sort_keyed({}, {}, {}, {})",
                            receiver.code, key, flag, args[0].code
                        )
                    };
                    let result = returned(Ret::List, code);
                    return if receiver.top {
                        result.with_fact(None)
                    } else {
                        result
                    };
                }
                if let Some((arrow, parts)) = lex {
                    let parts: Vec<String> = parts
                        .into_iter()
                        .map(|(key, descending, cp)| {
                            let key = self.key_lambda(arrow, key);
                            let flag = |b: bool| if b { "True" } else { "False" };
                            format!("({key}, {}, {})", flag(descending), flag(cp))
                        })
                        .collect();
                    let code = format!(
                        "_js_sort_lex({}, ({},), {})",
                        receiver.code,
                        parts.join(", "),
                        args[0].code
                    );
                    let result = returned(Ret::List, code);
                    return if receiver.top {
                        result.with_fact(None)
                    } else {
                        result
                    };
                }
                // J90-PF: `[...new Set(xs)].sort(cmp)`, `cmp` an adapter whose row promises
                // code-point order (not a local) and `Set` the builtin: `_js_sort_unique(xs, cmp)`,
                // which answers `sorted(set(xs))` for a list of `str`s and the general lowering's
                // own `_js_m_sort([*_JsSet(xs)], cmp)` for anything else.
                if method == "sort"
                    && !class_method
                    && !spread
                    && args.len() == 1
                    && simple_operand(&args[0].code)
                    && matches!(c.arguments[0].as_expression().map(strip),
                        Some(Expression::Identifier(id))
                            if self.codepoint_fns.contains(id.name.as_str())
                                && !self.is_scoped(id.name.as_str()))
                    && let Some(inner) = self.set_spread(&m.object, &receiver.code)
                {
                    let code = format!("_js_sort_unique({inner}, {})", args[0].code);
                    let result = returned(Ret::List, code);
                    return if receiver.top {
                        result.with_fact(None)
                    } else {
                        result
                    };
                }
                let optimistic = receiver.top || args.iter().any(|a| a.top);
                if !optimistic
                    && !spread
                    && (class_method || (args.len() >= min && args.len() <= max))
                    && let Some(fast) =
                        self.fast_method(method, &receiver, &args, as_statement, c, &m.object)
                {
                    return fast;
                }
                let arg_facts: Vec<Fact> = args.iter().map(Py::fact).collect();
                let args: Vec<String> = args.into_iter().map(|a| a.code).collect();
                if class_method && method != "toString" {
                    // J86: a compiled class also declares this name, so the receiver decides, as
                    // JS's prototype lookup does: the instance's method, else the builtin.
                    // (`_js_m_toString` dispatches to an instance itself.)
                    let mut all = vec![receiver.code, py_str(method), format!("_js_m_{method}")];
                    all.extend(args);
                    return Py::atom(format!("_js_dispatch({})", all.join(", ")));
                }
                // J91-3 (#341): what the call proves of its answer from the receiver's or the
                // argument's contents (`contents_fact`), taken before the codes are moved.
                let contents = if optimistic || class_method {
                    None
                } else {
                    contents_fact(method, &receiver, &arg_facts)
                };
                let mut all = vec![receiver.code];
                all.extend(args);
                let result = returned(ret, format!("_js_m_{method}({})", all.join(", ")));
                if optimistic {
                    return result.with_fact(None);
                }
                match contents {
                    Some(fact) => result.with_fact(Some(&fact)),
                    None => result,
                }
            }
            other => self.refuse(other.span(), "call of a computed callee"),
        }
    }

    /// J90-2: `(x) => Number.isInteger(x)` is `"integer"`, `(x) => typeof x === 'string'` (or `==`)
    /// is `"string"`: a one-parameter arrow whose body is exactly that test of its parameter, with
    /// `Number` the global. Any other callback is the general `every`.
    fn every_test(&self, e: &Expression<'_>) -> Option<&'static str> {
        let Expression::ArrowFunctionExpression(arrow) = strip(e) else {
            return None;
        };
        if arrow.r#async || arrow.params.items.len() != 1 || arrow.params.rest.is_some() {
            return None;
        }
        let BindingPattern::BindingIdentifier(param) = &arrow.params.items[0].pattern else {
            return None;
        };
        let is_param = |e: &Expression<'_>| matches!(strip(e), Expression::Identifier(id) if id.name == param.name);
        let body = arrow.body.as_expression()?;
        match strip(body) {
            Expression::CallExpression(call)
                if call.arguments.len() == 1
                    && !call.optional
                    && call.arguments[0].as_expression().is_some_and(is_param) =>
            {
                let Expression::StaticMemberExpression(m) = strip(&call.callee) else {
                    return None;
                };
                let number =
                    matches!(strip(&m.object), Expression::Identifier(id) if id.name == "Number");
                (number && m.property.name == "isInteger" && !self.is_local("Number"))
                    .then_some("integer")
            }
            Expression::BinaryExpression(b)
                if matches!(
                    b.operator,
                    BinaryOperator::StrictEquality | BinaryOperator::Equality
                ) =>
            {
                let typeof_param = |e: &Expression<'_>| {
                    matches!(strip(e), Expression::UnaryExpression(u)
                        if u.operator == UnaryOperator::Typeof && is_param(&u.argument))
                };
                let string = |e: &Expression<'_>| matches!(strip(e), Expression::StringLiteral(s) if s.value == "string");
                ((typeof_param(&b.left) && string(&b.right))
                    || (string(&b.left) && typeof_param(&b.right)))
                .then_some("string")
            }
            _ => None,
        }
    }

    /// J89-3: `(a, b) => t[b] - t[a] || a - b` (descending, `true`) or `(a, b) => t[a] - t[b] ||
    /// a - b` for `t` a Float64Array in scope (non-null assertions and parentheses allowed): the
    /// array's name and the direction. Any other comparator is not a key sort.
    fn key_comparator(&self, e: &Expression<'_>) -> Option<(String, bool)> {
        let Expression::ArrowFunctionExpression(arrow) = strip(e) else {
            return None;
        };
        if arrow.r#async || arrow.params.items.len() != 2 || arrow.params.rest.is_some() {
            return None;
        }
        let param = |k: usize| match &arrow.params.items[k].pattern {
            BindingPattern::BindingIdentifier(id) => Some(id.name.to_string()),
            _ => None,
        };
        let (a, b) = (param(0)?, param(1)?);
        if a == b {
            return None;
        }
        let body = arrow.body.as_expression()?;
        let Expression::LogicalExpression(or) = strip(body) else {
            return None;
        };
        if or.operator != LogicalOperator::Or {
            return None;
        }
        let name = |e: &Expression<'_>| match strip(e) {
            Expression::Identifier(id) => Some(id.name.to_string()),
            _ => None,
        };
        fn difference<'b, 'a>(
            e: &'b Expression<'a>,
        ) -> Option<(&'b Expression<'a>, &'b Expression<'a>)> {
            match strip(e) {
                Expression::BinaryExpression(d) if d.operator == BinaryOperator::Subtraction => {
                    Some((&d.left, &d.right))
                }
                _ => None,
            }
        }
        // The tie-break: `a - b`.
        let (l, r) = difference(&or.right)?;
        if name(l)? != a || name(r)? != b {
            return None;
        }
        // The key: `t[x] - t[y]` with {x, y} = {a, b}.
        let (l, r) = difference(&or.left)?;
        let element = |e: &Expression<'_>| match strip(e) {
            Expression::ComputedMemberExpression(m) if !m.optional => {
                Some((self.typed_array(&m.object)?, name(&m.expression)?))
            }
            _ => None,
        };
        let ((t1, x), (t2, y)) = (element(l)?, element(r)?);
        if t1 != t2 || a == t1 || b == t1 {
            return None;
        }
        if x == b && y == a {
            Some((t1, true))
        } else if x == a && y == b {
            Some((t1, false))
        } else {
            None
        }
    }

    /// J90-P: `(a, b) => k(a) - k(b)` (ascending) or `(a, b) => k(b) - k(a)` (descending), where
    /// `k(x)` reads only `x`, other bindings, member reads and `.get(...)` (no compiled class
    /// declares `get`, so it is a Map's): an expression with no effect, whose value for an item is
    /// the same however often it is computed. The arrow, `k(a)` and whether it is descending.
    fn keyed_comparator<'b, 'a>(
        &self,
        e: &'b Expression<'a>,
    ) -> Option<(&'b ArrowFunctionExpression<'a>, &'b Expression<'a>, bool)> {
        let Expression::ArrowFunctionExpression(arrow) = strip(e) else {
            return None;
        };
        if arrow.r#async || arrow.params.items.len() != 2 || arrow.params.rest.is_some() {
            return None;
        }
        if arrow.params.items.iter().any(|p| p.initializer.is_some()) {
            return None;
        }
        let param = |k: usize| match &arrow.params.items[k].pattern {
            BindingPattern::BindingIdentifier(id) => Some(id.name.to_string()),
            _ => None,
        };
        let (a, b) = (param(0)?, param(1)?);
        if a == b || matches!(&arrow.body, ArrowFunctionBody::FunctionBody(_)) {
            return None;
        }
        let Expression::BinaryExpression(d) = strip(arrow.body.as_expression()?) else {
            return None;
        };
        if d.operator != BinaryOperator::Subtraction {
            return None;
        }
        // `l` is `k(b)` and `r` is `k(a)`: descending; the other way round: ascending.
        if self.swapped(&d.left, &d.right, &a, &b) {
            return Some((arrow, &d.right, true));
        }
        if self.swapped(&d.right, &d.left, &a, &b) {
            return Some((arrow, &d.left, false));
        }
        None
    }

    /// J90-P2: the `x` of `createHash(alg).update(x, 'utf8').digest('hex')`, `createHash` the
    /// node:crypto adapter (not a local) and `alg` the literal `'sha256'` or `'sha1'`: None for
    /// anything else (the calls are then lowered one by one).
    fn hash_chain<'b, 'a>(
        &self,
        c: &'b CallExpression<'a>,
        m: &'b StaticMemberExpression<'a>,
    ) -> Option<(&'static str, &'b Expression<'a>)> {
        let literal = |a: &Argument<'_>, want: &[&'static str]| -> Option<&'static str> {
            match a.as_expression().map(strip) {
                Some(Expression::StringLiteral(s)) => want.iter().copied().find(|w| s.value == *w),
                _ => None,
            }
        };
        if c.optional
            || m.optional
            || c.arguments.len() != 1
            || literal(&c.arguments[0], &["hex"]).is_none()
        {
            return None;
        }
        let Expression::CallExpression(update) = strip(&m.object) else {
            return None;
        };
        let Expression::StaticMemberExpression(um) = strip(&update.callee) else {
            return None;
        };
        if update.optional
            || um.optional
            || um.property.name != "update"
            || update.arguments.len() != 2
            || literal(&update.arguments[1], &["utf8"]).is_none()
        {
            return None;
        }
        let Expression::CallExpression(create) = strip(&um.object) else {
            return None;
        };
        let Expression::Identifier(f) = strip(&create.callee) else {
            return None;
        };
        let adapter = self.hash_fns.contains(f.name.as_str()) && !self.is_scoped(f.name.as_str());
        if !adapter || create.optional || create.arguments.len() != 1 {
            return None;
        }
        let alg = literal(&create.arguments[0], &["sha256", "sha1"])?;
        Some((alg, update.arguments[0].as_expression()?))
    }

    /// J91-2 (#341): the arguments of `parseInt(H.slice(0, N), 16)`, `H` a `hash_chain` and `N` a
    /// whole literal in `[1, 13]`: the algorithm, the hashed value and N. A sha1 hex digest has
    /// 40 digits and a sha256 one 64, so the slice is N digits, all `[0-9a-f]`, and `parseInt`
    /// reads every one of them: the int they spell, below 16**13 = 2**52.
    fn hash_int_chain<'b, 'a>(
        &self,
        c: &'b CallExpression<'a>,
    ) -> Option<(&'static str, &'b Expression<'a>, u32)> {
        let number = |a: &Argument<'_>| match a.as_expression().map(strip) {
            Some(Expression::NumericLiteral(n)) if n.value.fract() == 0.0 => Some(n.value),
            _ => None,
        };
        if c.optional || c.arguments.len() != 2 || number(&c.arguments[1]) != Some(16.0) {
            return None;
        }
        let Some(Expression::CallExpression(slice)) = c.arguments[0].as_expression().map(strip)
        else {
            return None;
        };
        let Expression::StaticMemberExpression(sm) = strip(&slice.callee) else {
            return None;
        };
        if slice.optional
            || sm.optional
            || sm.property.name != "slice"
            || slice.arguments.len() != 2
            || number(&slice.arguments[0]) != Some(0.0)
        {
            return None;
        }
        let digits = number(&slice.arguments[1]).filter(|n| (1.0..=13.0).contains(n))?;
        let Expression::CallExpression(digest) = strip(&sm.object) else {
            return None;
        };
        let Expression::StaticMemberExpression(dm) = strip(&digest.callee) else {
            return None;
        };
        if dm.property.name != "digest" {
            return None;
        }
        let (alg, data) = self.hash_chain(digest, dm)?;
        Some((alg, data, digits as u32))
    }

    /// J90-P2: `(a, b) => c1 || c2 || ... || cn`, each `ci` a key difference `k(a) - k(b)` /
    /// `k(b) - k(a)` or a code-point comparison `cmp(k(a), k(b))` / `cmp(k(b), k(a))` (`cmp` an
    /// adapter whose row promises `compare-codepoints`, not a local), every `k` pure as for
    /// `keyed_comparator`: the arrow and per part its `k(a)`, whether it is descending and whether
    /// it is a code-point part. Only a chain of two or more parts, or one code-point part (one
    /// difference alone is `keyed_comparator`'s).
    #[allow(clippy::type_complexity)]
    fn lex_comparator<'b, 'a>(
        &self,
        e: &'b Expression<'a>,
    ) -> Option<(
        &'b ArrowFunctionExpression<'a>,
        Vec<(&'b Expression<'a>, bool, bool)>,
    )> {
        let Expression::ArrowFunctionExpression(arrow) = strip(e) else {
            return None;
        };
        if arrow.r#async || arrow.params.items.len() != 2 || arrow.params.rest.is_some() {
            return None;
        }
        if arrow.params.items.iter().any(|p| p.initializer.is_some()) {
            return None;
        }
        let param = |k: usize| match &arrow.params.items[k].pattern {
            BindingPattern::BindingIdentifier(id) => Some(id.name.to_string()),
            _ => None,
        };
        let (a, b) = (param(0)?, param(1)?);
        if a == b || matches!(&arrow.body, ArrowFunctionBody::FunctionBody(_)) {
            return None;
        }
        fn chain<'b, 'a>(e: &'b Expression<'a>, out: &mut Vec<&'b Expression<'a>>) {
            match strip(e) {
                Expression::LogicalExpression(or) if or.operator == LogicalOperator::Or => {
                    chain(&or.left, out);
                    chain(&or.right, out);
                }
                other => out.push(other),
            }
        }
        let mut parts = Vec::new();
        chain(arrow.body.as_expression()?, &mut parts);
        let codepoint = |name: &str| self.codepoint_fns.contains(name) && !self.is_scoped(name);
        let mut keys = Vec::new();
        for part in parts {
            let (l, r, cp) = match part {
                Expression::BinaryExpression(d) if d.operator == BinaryOperator::Subtraction => {
                    (&d.left, &d.right, false)
                }
                Expression::CallExpression(c)
                    if !c.optional
                        && c.arguments.len() == 2
                        && matches!(strip(&c.callee), Expression::Identifier(id) if codepoint(id.name.as_str())) =>
                {
                    (
                        c.arguments[0].as_expression()?,
                        c.arguments[1].as_expression()?,
                        true,
                    )
                }
                _ => return None,
            };
            if self.swapped(l, r, &a, &b) {
                keys.push((r, true, cp));
            } else if self.swapped(r, l, &a, &b) {
                keys.push((l, false, cp));
            } else {
                return None;
            }
        }
        (keys.len() >= 2 || keys.first().is_some_and(|k| k.2)).then_some((arrow, keys))
    }

    /// J90-P: `l` is `r` with `a` read as `b`: the same pure expression of the other parameter.
    fn swapped(&self, l: &Expression<'_>, r: &Expression<'_>, a: &str, b: &str) -> bool {
        match (strip(l), strip(r)) {
            (Expression::Identifier(x), Expression::Identifier(y)) => {
                (x.name == b && y.name == a)
                    || (x.name == y.name && x.name != a && x.name != b && x.name != "undefined")
            }
            (Expression::NumericLiteral(x), Expression::NumericLiteral(y)) => {
                x.value.to_bits() == y.value.to_bits()
            }
            (Expression::StringLiteral(x), Expression::StringLiteral(y)) => x.value == y.value,
            (Expression::StaticMemberExpression(x), Expression::StaticMemberExpression(y)) => {
                !x.optional
                    && !y.optional
                    && x.property.name == y.property.name
                    && self.swapped(&x.object, &y.object, a, b)
            }
            // (A Float64Array's element is J89-3's key sort, `_js_sort_by_f64`, or the general one.)
            (Expression::ComputedMemberExpression(x), Expression::ComputedMemberExpression(y)) => {
                !x.optional
                    && !y.optional
                    && self.typed_array(&x.object).is_none()
                    && self.swapped(&x.object, &y.object, a, b)
                    && self.swapped(&x.expression, &y.expression, a, b)
            }
            (Expression::CallExpression(x), Expression::CallExpression(y)) => {
                fn get<'b, 'a>(
                    c: &'b CallExpression<'a>,
                ) -> Option<(&'b Expression<'a>, &'b Expression<'a>)> {
                    match strip(&c.callee) {
                        Expression::StaticMemberExpression(m)
                            if !c.optional && !m.optional && m.property.name == "get" =>
                        {
                            match c.arguments.as_slice() {
                                [arg] => arg.as_expression().map(|e| (&m.object, e)),
                                _ => None,
                            }
                        }
                        _ => None,
                    }
                }
                let (Some((xo, xa)), Some((yo, ya))) = (get(x), get(y)) else {
                    return false;
                };
                !self.ctx.class_methods.contains("get")
                    && !self.imported_methods.contains("get")
                    && self.swapped(xo, yo, a, b)
                    && self.swapped(xa, ya, a, b)
            }
            _ => false,
        }
    }

    /// J90-P: `lambda <a>, *_: <k(a)>`, `k(a)` lowered in a scope of the comparator's first
    /// parameter alone (as the comparator's own lowering binds it).
    /// J90-PF: the lowered `xs` of an array literal `[...new Set(xs)]` (one spread element, `Set`
    /// the builtin, one plain argument) whose lowering `code` is exactly `[*_JsSet(<xs>)]`; None
    /// for any other array or text.
    fn set_spread(&self, object: &Expression<'_>, code: &str) -> Option<String> {
        let Expression::ArrayExpression(array) = strip(object) else {
            return None;
        };
        let [ArrayExpressionElement::SpreadElement(spread)] = array.elements.as_slice() else {
            return None;
        };
        let Expression::NewExpression(n) = strip(&spread.argument) else {
            return None;
        };
        let builtin = matches!(strip(&n.callee), Expression::Identifier(id)
            if id.name == "Set" && !self.is_local("Set") && !self.classes.contains_key("Set"));
        if !builtin
            || n.arguments.len() != 1
            || matches!(n.arguments[0], Argument::SpreadElement(_))
        {
            return None;
        }
        let inner = code.strip_prefix("[*_JsSet(")?.strip_suffix(")]")?;
        // The text between is one balanced expression (no `), (` splitting it into two).
        let mut depth = 0i32;
        let mut quote: Option<char> = None;
        let mut escaped = false;
        for ch in inner.chars() {
            if let Some(q) = quote {
                if escaped {
                    escaped = false;
                } else if ch == '\\' {
                    escaped = true;
                } else if ch == q {
                    quote = None;
                }
                continue;
            }
            match ch {
                '"' | '\'' => quote = Some(ch),
                '(' | '[' | '{' => depth += 1,
                ')' | ']' | '}' => {
                    depth -= 1;
                    if depth < 0 {
                        return None;
                    }
                }
                _ => {}
            }
        }
        (depth == 0 && quote.is_none() && !inner.is_empty()).then(|| inner.to_string())
    }

    fn key_lambda(&mut self, arrow: &ArrowFunctionExpression<'_>, key: &Expression<'_>) -> String {
        let BindingPattern::BindingIdentifier(id) = &arrow.params.items[0].pattern else {
            unreachable!("keyed_comparator matched a plain parameter")
        };
        let py = py_name(id.name.as_str(), false, false);
        self.claim(id.name.as_str(), &py, id.span);
        let mut scope = HashSet::new();
        scope.insert(id.name.to_string());
        self.push_scope(scope, arrow.span.start);
        self.bind(id.name.as_str(), Fact::default());
        self.rets.push(None);
        self.in_callback += 1;
        let value = self.expr(key);
        self.in_callback -= 1;
        self.rets.pop();
        self.pop_scope();
        format!("lambda {py}, *_: {}", value.at(TERNARY))
    }

    fn static_call(&mut self, object: &str, method: &str, c: &CallExpression<'_>) -> Py {
        // J88-2: a function of a namespace-imported Node module, or a Node global's static
        // (`Buffer.from`): its adapter row, called with the arguments as given.
        let adapter = match self.namespaces.get(object) {
            Some(module) => {
                let module = module.clone();
                match self.ctx.adapters.import(&module, method) {
                    Some(a) if a.kind == AdapterKind::Function => Some(a),
                    _ => {
                        let construct = format!("{module} function {method}: no declared adapter");
                        return self.refuse(c.span, construct);
                    }
                }
            }
            None => self
                .ctx
                .adapters
                .global(&format!("{object}.{method}"))
                .filter(|a| a.kind == AdapterKind::Function),
        };
        if let Some(adapter) = adapter {
            self.imports
                .entry(self.ctx.adapter_module.clone())
                .or_default()
                .insert(adapter.py_name.to_string());
            let Some(args) = self.args(&c.arguments, None, false) else {
                return Py::atom("None");
            };
            return Py::atom(format!("{}({})", adapter.py_name, args.join(", ")));
        }
        // J88-2: `Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)`, the one
        // spelling of a synchronous sleep: nothing can notify that fresh buffer.
        if object == "Atomics" && method == "wait" && !self.is_local("Atomics") {
            let fresh = c.arguments.len() == 4
                && matches!(c.arguments[0].as_expression().map(strip), Some(Expression::NewExpression(n))
                    if matches!(strip(&n.callee), Expression::Identifier(i) if i.name == "Int32Array")
                        && n.arguments.len() == 1
                        && matches!(n.arguments[0].as_expression().map(strip), Some(Expression::NewExpression(inner))
                            if matches!(strip(&inner.callee), Expression::Identifier(i) if i.name == "SharedArrayBuffer")))
                && matches!(c.arguments[1].as_expression().map(strip), Some(Expression::NumericLiteral(n)) if n.value == 0.0)
                && matches!(c.arguments[2].as_expression().map(strip), Some(Expression::NumericLiteral(n)) if n.value == 0.0);
            if !fresh {
                return self.refuse(c.span, "Atomics.wait other than a sleep on a fresh buffer");
            }
            let ms = self.expr(c.arguments[3].as_expression().expect("checked above"));
            return returned(Ret::Str, format!("_js_sleep_ms({})", ms.code));
        }
        // J88-2: `JSON.stringify(value, replacer, space)`.
        if object == "JSON" && method == "stringify" && (2..=3).contains(&c.arguments.len()) {
            let Some(args) = self.args(&c.arguments, None, false) else {
                return Py::atom("None");
            };
            return Py::atom(format!("_js_json_stringify_with({})", args.join(", ")));
        }
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
        // J90-P3: `Array.isArray(x)` is `_js_is_array`'s own test, inline (no call).
        if helper == "_js_is_array" && args.len() == 1 {
            return Py::boolean(format!("isinstance({}, list)", args[0]), ATOM);
        }
        // J90-P3: `Number.isInteger(x)`, `x` a name or an element read (evaluated twice, no
        // effect): a plain int a double holds exactly is `_js_number_is_integer`'s first answer
        // (True), inline; anything else asks it.
        if helper == "_js_number_is_integer"
            && args.len() == 1
            && c.arguments[0]
                .as_expression()
                .is_some_and(|e| self.twice_safe(e))
        {
            let x = &args[0];
            return Py::boolean(
                format!(
                    "(type({x}) is int and -2**53 <= {x} <= 2**53 or _js_number_is_integer({x}))"
                ),
                ATOM,
            );
        }
        returned(ret, format!("{helper}({})", args.join(", ")))
    }

    /// J90-P: the `x` of `Object.entries(x)` (`Object` the global), or of `f(x)` where `f` is a
    /// module `const` arrow `(v) => Object.entries(v)` no scope shadows.
    fn entries_source<'b, 'a>(&self, e: &'b Expression<'a>) -> Option<&'b Expression<'a>> {
        let Expression::CallExpression(c) = strip(e) else {
            return None;
        };
        let [arg] = c.arguments.as_slice() else {
            return None;
        };
        let arg = arg.as_expression()?;
        if c.optional {
            return None;
        }
        let ok = match strip(&c.callee) {
            Expression::StaticMemberExpression(m) => {
                !m.optional
                    && m.property.name == "entries"
                    && matches!(strip(&m.object), Expression::Identifier(o)
                        if o.name == "Object" && !self.is_local("Object"))
            }
            Expression::Identifier(f) => {
                self.entries_aliases.contains(f.name.as_str()) && !self.is_scoped(f.name.as_str())
            }
            _ => false,
        };
        ok.then_some(arg)
    }

    fn new_expr(&mut self, n: &NewExpression<'_>) -> Py {
        let Expression::Identifier(id) = strip(&n.callee) else {
            let construct = format!("new {}", self.text(n.callee.span()));
            return self.refuse(n.span, construct);
        };
        let name = id.name.as_str();
        if name == "Float64Array" && !self.is_local(name) {
            return self.refuse(
                n.span,
                "new Float64Array anywhere but a const's initializer",
            );
        }
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
                    // J90-P: `new Map(Object.entries(x))` (or through a module `const` arrow
                    // `(v) => Object.entries(v)`): the Map built from the object's own keys at
                    // once (`_js_map_entries`), not through the entries array it would discard.
                    if name == "Map"
                        && let Some(object) = n.arguments.first().and_then(|a| a.as_expression())
                        && let Some(source) = self.entries_source(object)
                    {
                        let source = self.expr(source);
                        // J91-1: `_js_map_entries` answers a `_JsMap` itself, or raises.
                        return Py {
                            is_map: true,
                            ..Py::atom(format!("_js_map_entries({})", source.code))
                        };
                    }
                    Some(if name == "Map" { "_JsMap" } else { "_JsSet" }.to_string())
                }
                // J86: the built-in Errors the codec throws.
                "Error" | "TypeError" | "RangeError" => {
                    if n.arguments.len() > 1 {
                        return self.refuse(n.span, "argument count for new Error");
                    }
                    Some(
                        match name {
                            "Error" => "_JsError",
                            "TypeError" => "_JsTypeError",
                            _ => "_JsRangeError",
                        }
                        .to_string(),
                    )
                }
                "RegExp" => return self.dynamic_regex(n),
                _ => match self.ctx.adapters.global(name) {
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
        let Some(lowered) = self.args_py(&n.arguments, None, false) else {
            return Py::atom("None");
        };
        let args: Vec<String> = lowered.iter().map(|a| a.code.clone()).collect();
        // J91-1 (#341): the builtin `Map` (not a compiled class or a local of that name, both
        // handled above) constructs a `_JsMap` itself, or raises.
        let builtin_map = name == "Map" && !shadowed && !self.classes.contains_key(name);
        let builtin_set = name == "Set" && !shadowed && !self.classes.contains_key(name);
        // J91-3 (#341): a Map or Set just made is `own`. One made empty holds nothing yet, so what
        // its entries are is vacuous (`Fact::top`); a Set made from a list proven `own` or a frozen
        // constant's elements, every one a `str`, holds exactly those `str`s (`_JsSet` keeps a
        // `str` item as itself). Anything else proves nothing of its contents.
        let made = (builtin_map && class == "_JsMap") || (builtin_set && class == "_JsSet");
        let elem = if !made {
            None
        } else if lowered.is_empty() {
            Some(Box::new(Fact::top()))
        } else if builtin_set
            && let [items] = lowered.as_slice()
            && items.top
        {
            // Optimistic while the items are.
            Some(Box::new(Fact::top()))
        } else if builtin_set
            && let [items] = lowered.as_slice()
            && items.is_list
            && items.elem.as_ref().is_some_and(|e| e.top || e.str_)
        {
            Some(Box::new(Fact::str_()))
        } else {
            None
        };
        Py {
            is_map: builtin_map && class == "_JsMap",
            own: made,
            elem,
            ..Py::atom(format!("{class}({})", args.join(", ")))
        }
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
        // J91-3 (#341): a `g` literal is a `_JsGlobalRegExp` (`_JS_RE_<i>` is bound to one).
        Py {
            pure: true,
            is_regex: !global,
            is_gregex: global,
            ..Py::atom(format!("_JS_RE_{index}"))
        }
    }
}

// -------------------------------------------------------------------- J86: modules and classes

impl<'s> Lowerer<'s> {
    /// A value import: from a compiled module (`from .<module> import <names>`), or through the
    /// adapter seam (`adapters.rs`). Anything else is refused, naming the import.
    fn import(&mut self, i: &ImportDeclaration<'_>) {
        self.import_type_fields(i);
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
            // J88-2: `import * as fs from 'node:fs'`: `fs.name(...)` is that module's adapter row.
            if let ImportDeclarationSpecifier::ImportNamespaceSpecifier(ns) = specifier
                && spec.starts_with("node:")
            {
                let local = ns.local.name.as_str();
                self.claim(local, local, ns.span);
                self.namespaces.insert(local.to_string(), spec.to_string());
                continue;
            }
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
                let cyclic = resolved
                    .as_ref()
                    .is_some_and(|path| self.ctx.cyclic_imports.contains(path));
                let into = if cyclic {
                    self.cyclic_py.insert(py.clone());
                    &mut self.late_imports
                } else {
                    &mut self.imports
                };
                into.entry(format!(".{}", module.py_module))
                    .or_default()
                    .insert(py.clone());
                self.globals.insert(local.to_string(), py.clone());
                if let Some(fact) = module.rets.get(local) {
                    self.imported_rets.insert(local.to_string(), fact.clone());
                }
                if module.generators.contains(local) {
                    self.generator_fns.insert(local.to_string());
                }
                if is_class {
                    self.classes.insert(local.to_string(), py);
                }
                continue;
            }
            match resolved
                .as_deref()
                .and_then(|path| self.ctx.adapters.import(path, local))
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
                            if adapter.contract == Some(Contract::CompareCodepoints) {
                                self.codepoint_fns.insert(local.to_string());
                            }
                            if adapter.contract == Some(Contract::Str) {
                                self.str_fns.insert(local.to_string());
                            }
                            if adapter.is(Some("node:crypto"), "createHash") {
                                self.hash_fns.insert(local.to_string());
                            }
                        }
                        AdapterKind::Constant => {}
                        // J89-4a: its methods dispatch in this module only.
                        AdapterKind::ImportedClass(methods) => {
                            self.classes.insert(local.to_string(), py);
                            self.imported_methods
                                .extend(methods.iter().map(|m| m.to_string()));
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

    /// J89-5: a type imported from a compiled module of the call (`import type { Fact }`,
    /// `import { type Pool }`) declares the data fields it declares there, under the local name. A
    /// type the module itself declares under that name keeps its own (TypeScript refuses both).
    fn import_type_fields(&mut self, i: &ImportDeclaration<'_>) {
        let Some(spec) = i.source.value.as_str() else {
            return;
        };
        let Some(specifiers) = &i.specifiers else {
            return;
        };
        let Some(module) = resolve_specifier(&self.ctx.path, spec)
            .as_ref()
            .and_then(|path| self.ctx.modules.get(path))
        else {
            return;
        };
        for specifier in specifiers {
            let ImportDeclarationSpecifier::ImportSpecifier(s) = specifier else {
                continue;
            };
            if !(i.import_kind.is_type() || s.import_kind.is_type()) {
                continue;
            }
            let imported = s.imported.name();
            let Some(fields) = module.type_fields.get(imported.as_str()) else {
                continue;
            };
            let local = s.local.name.to_string();
            if !self.types.fields.contains_key(&local) {
                self.types.fields.insert(local.clone(), fields.clone());
                self.types.data.insert(local);
            }
        }
    }

    /// `export { a, b }`: each a module-level name (declared or imported), exported as itself.
    /// J90-3: `export { a, type T } from './m.js'` (storage/index.ts): each value name imported
    /// as `import { a } from './m.js'` would import it (a compiled module of the call, or an
    /// adapter row), then exported. A renamed re-export, `export *`, and a name already bound here
    /// are refused. Another compiled module cannot import a name through the re-export (the
    /// re-exporting module's export table lists only what it declares): such an import is refused
    /// as one the module does not export.
    fn re_export(&mut self, e: &ExportFromDeclaration<'_>) {
        if e.with_clause.is_some() {
            self.refuse(e.span, "re-export with an import attribute");
            return;
        }
        let Some(spec) = e.source.value.as_str() else {
            self.refuse(e.span, "re-export specifier with a lone surrogate");
            return;
        };
        let resolved = resolve_specifier(&self.ctx.path, spec);
        for specifier in &e.specifiers {
            if specifier.export_kind.is_type() {
                continue;
            }
            let local = specifier.local.name();
            if specifier.exported.name() != local {
                self.refuse(specifier.span, "renamed re-export");
                continue;
            }
            let local = local.as_str();
            let compiled = resolved
                .as_ref()
                .and_then(|path| self.ctx.modules.get(path))
                .cloned();
            let py = if let Some(module) = compiled {
                let Some((py, _)) = module.names.get(local).cloned() else {
                    let construct = format!(
                        "re-export of {local} from {spec}, which that module does not export"
                    );
                    self.refuse(specifier.span, construct);
                    continue;
                };
                let cyclic = resolved
                    .as_ref()
                    .is_some_and(|path| self.ctx.cyclic_imports.contains(path));
                let into = if cyclic {
                    self.cyclic_py.insert(py.clone());
                    &mut self.late_imports
                } else {
                    &mut self.imports
                };
                into.entry(format!(".{}", module.py_module))
                    .or_default()
                    .insert(py.clone());
                py
            } else if let Some(adapter) = resolved
                .as_deref()
                .and_then(|path| self.ctx.adapters.import(path, local))
            {
                let py = adapter.py_name.to_string();
                self.imports
                    .entry(self.ctx.adapter_module.clone())
                    .or_default()
                    .insert(py.clone());
                py
            } else {
                let construct = format!(
                    "re-export of {local} from {spec}: no compiled module and no declared adapter"
                );
                self.refuse(specifier.span, construct);
                continue;
            };
            self.claim(local, &py, specifier.span);
            if !self.exports.contains(&py) {
                self.exports.push(py);
            }
        }
    }

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
        let start = out.len();
        self.class_decl_body(c, out);
        let lines = out.split_off(start);
        out.extend(hoist_closure_methods(lines));
    }

    fn class_decl_body(&mut self, c: &Class<'_>, out: &mut Vec<String>) {
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
        // J87-3: `extends` an Error class visible here (an adapter `ErrorClass` such as a host's
        // `AppError`, or one declared above) as well as `Error` itself.
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
        let mut statics: Vec<&MethodDefinition<'_>> = Vec::new();
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
                    if m.computed || !m.decorators.is_empty() {
                        self.refuse(m.span, "static or computed method");
                        continue;
                    }
                    // J88-2: a static METHOD (not a getter, not a field) is a `@staticmethod`
                    // whose body has no `this`; it is not an own member of an instance.
                    if m.r#static {
                        if m.kind != MethodDefinitionKind::Method
                            || m.value.generator
                            || m.value.r#async
                            || m.value.body.is_none()
                        {
                            self.refuse(m.span, "static or computed method");
                            continue;
                        }
                        statics.push(m);
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
        // J90-P7: every class ts2py writes is an ordinary Python class under mypyc too (its base,
        // `_JsObject` or an Error, is one, and `_js_object_get` reads its `__dict__`); the three
        // reflective lists are class attributes, so they say so.
        out.push("@_mypyc_attr(native_class=False)".to_string());
        out.push(format!("class {name}({base}):"));
        out.push(format!(
            "    _js_name: _ClassVar[str] = {}",
            py_str(id.name.as_str())
        ));
        out.push(format!(
            "    _js_own: _ClassVar[frozenset[str]] = {}",
            set(&own)
        ));
        out.push(format!(
            "    _js_own_methods: _ClassVar[frozenset[str]] = {}",
            set(&own_methods)
        ));

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
            // J90-P7: mypyc compiles a property only with a return annotation.
            let returns = if m.kind == MethodDefinitionKind::Get {
                " -> object"
            } else {
                ""
            };
            out.push(format!("    def {key}({}){returns}:", signature.join(", ")));
            self.param_defaults(&f.params, 2, out);
            self.hoist_params(&f.params, 2, out);
            self.block(statements, 2, out);
            if !ends_in_exit(statements) {
                out.push("        return _JS_UNDEFINED".to_string());
            }
            self.rets.pop();
            self.pop_scope();
        }
        // J88-2: static methods, lowered with no class context (so `this` is refused).
        let instance_ctx = self.class_ctx.take();
        for m in statics {
            let key = match self.member_name(&m.key, m.span, is_error) {
                Some(key) => key,
                None => continue,
            };
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
            out.push("    @staticmethod".to_string());
            out.push(format!("    def {key}({}):", join_params(&names)));
            self.param_defaults(&f.params, 2, out);
            self.hoist_params(&f.params, 2, out);
            self.block(statements, 2, out);
            if !ends_in_exit(statements) {
                out.push("        return _JS_UNDEFINED".to_string());
            }
            self.rets.pop();
            self.pop_scope();
        }
        drop(instance_ctx);
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
            "RangeError" if !self.is_local(name) => Some("_JsRangeError".to_string()),
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

    /// J88-2: an arrow used as a value: a loose nested `def` emitted before the statement.
    fn hoisted_arrow(&mut self, a: &ArrowFunctionExpression<'_>) -> Py {
        if self.in_callback > 0 || self.scopes.is_empty() {
            return self.refuse(a.span, "arrow function outside a callback argument");
        }
        let name = format!("_js_fn{}", self.tmp);
        self.tmp += 1;
        let mut lines = Vec::new();
        let indent = self.cur_indent;
        self.nested_def_with(&name, a, indent, &mut lines, true);
        self.pre.extend(lines);
        Py::atom(name)
    }

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
        self.nested_def_with(name, a, indent, out, false);
    }

    /// `loose` (J88-2, an arrow used as a value): every parameter defaults to `undefined`.
    /// All arrows swallow extra arguments, including those bound to a local `const`.
    fn nested_def_with(
        &mut self,
        name: &str,
        a: &ArrowFunctionExpression<'_>,
        indent: usize,
        out: &mut Vec<String>,
        loose: bool,
    ) {
        if a.r#async {
            self.refuse(a.span, "async function");
            return;
        }
        if self.breaks.contains(&BreakTarget::Loop) {
            self.refuse(a.span, "function defined inside a loop");
            return;
        }
        let mut names = self.params(&a.params);
        if loose {
            for (_, py) in names.iter_mut() {
                if !py.ends_with("=_JS_UNDEFINED") {
                    py.push_str("=_JS_UNDEFINED");
                }
            }
        }
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
        let saved_generator = std::mem::replace(&mut self.in_generator, false);
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
        self.in_generator = saved_generator;
        let (_, nonlocals) = self.defs.pop().expect("pushed above");
        self.rets.pop();
        self.pop_scope();
        let params = join_params(&names);
        // Use the reserved prefix so a source parameter named `_` cannot collide.
        let signature = if params.is_empty() {
            "*_js_extra".to_string()
        } else {
            format!("{params}, *_js_extra")
        };
        out.push(format!("{}def {name}({signature}):", pad(indent)));
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
            // J89-2: a module-level `let`, assigned from a module function: declared `global`
            // there. From a nested function it is refused (it would need `global` in a closure,
            // which is not worth a rule while no source does it).
            if self.module_lets.contains(name)
                && self.defs.is_empty()
                && let Some(writes) = self.global_writes.last_mut()
            {
                writes.insert(name.to_string());
                return Py::atom(self.globals[name].clone());
            }
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
            self.observed
                .assign_spans
                .entry(key.clone())
                .or_default()
                .insert(span.start);
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
/// `.ts` it is compiled from (`src/memory/pyyaml.ts`). None for a bare specifier.
/// J90-2: the compiled modules of the call `program` imports a value from (a type-only import
/// binds nothing at run time and is no edge of an import cycle).
pub fn compiled_imports(
    program: &Program<'_>,
    path: &str,
    modules: &HashMap<String, ModuleExports>,
) -> HashSet<String> {
    let mut out = HashSet::new();
    for stmt in &program.body {
        // J90-3: a value re-export binds what an import of the same names would.
        if let Statement::ExportFromDeclaration(e) = stmt
            && !e.export_kind.is_type()
            && e.specifiers.iter().any(|s| !s.export_kind.is_type())
        {
            if let Some(spec) = e.source.value.as_str()
                && let Some(target) = resolve_specifier(path, spec)
                && modules.contains_key(&target)
            {
                out.insert(target);
            }
            continue;
        }
        let Statement::ImportDeclaration(i) = stmt else {
            continue;
        };
        if i.import_kind.is_type() {
            continue;
        }
        let values = i.specifiers.as_ref().is_some_and(|specifiers| {
            specifiers.iter().any(|s| match s {
                ImportDeclarationSpecifier::ImportSpecifier(s) => !s.import_kind.is_type(),
                _ => true,
            })
        });
        if !values {
            continue;
        }
        if let Some(spec) = i.source.value.as_str()
            && let Some(target) = resolve_specifier(path, spec)
            && modules.contains_key(&target)
        {
            out.insert(target);
        }
    }
    out
}

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
/// J89-4a: the names of a module's top-level generator functions (`function*`), exported or not.
pub fn generator_names(program: &Program<'_>) -> HashSet<String> {
    let mut out = HashSet::new();
    for stmt in &program.body {
        let decl = match stmt {
            Statement::ExportDeclaration(e) => Some(&e.declaration),
            _ => stmt.as_declaration(),
        };
        if let Some(Declaration::FunctionDeclaration(f)) = decl
            && f.generator
            && let Some(id) = &f.id
        {
            out.insert(id.name.to_string());
        }
    }
    out
}

/// What a module offers the others of its call: its exports, the method names its EXPORTED
/// classes declare (they reach every module of the call), and the method names its other classes
/// declare (J89-5a: they dispatch in this module only, as an `ImportedClass` adapter's do).
pub type ModuleScan = (
    HashMap<String, (String, bool)>,
    HashSet<String>,
    HashSet<String>,
);

pub fn scan_module(program: &Program<'_>) -> ModuleScan {
    let mut exports = HashMap::new();
    let mut class_methods: Vec<(String, Vec<String>)> = Vec::new();
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
                // J89-2: a module-level `let` is a live binding another compiled module would
                // import as a snapshot (`from .m import X` copies the value once), so it is not
                // offered to them: such an import is refused as one the module does not export.
                if v.kind != VariableDeclarationKind::Const {
                    continue;
                }
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
                let mut declared = Vec::new();
                for element in &c.body.body {
                    if let ClassElement::MethodDefinition(m) = element
                        && m.kind == MethodDefinitionKind::Method
                        && let Some(name) = property_key_name(&m.key)
                    {
                        declared.push(name);
                    }
                }
                // An anonymous class cannot be named by an export (and is refused when lowered).
                let name =
                    c.id.as_ref()
                        .map_or(String::new(), |id| id.name.to_string());
                class_methods.push((name, declared));
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
    // J89-5a: a class no export names is reachable from another module only as a value a function
    // returned. There a call of one of its methods that a builtin shares (`row.get(t)`) is the
    // builtin's helper, which refuses an instance at run time (`_js_outside`), and a read of one as
    // a value is refused by `_js_object_get`: never a different answer. So its method names stay
    // in its own module, and the other modules' builtin calls are not dispatched for it.
    let mut methods = HashSet::new();
    let mut private = HashSet::new();
    for (name, declared) in class_methods {
        let exported = exports.get(&name).is_some_and(|(_, is_class)| *is_class);
        if exported {
            methods.extend(declared);
        } else {
            private.extend(declared);
        }
    }
    (exports, methods, private)
}

// -------------------------------------------------------------------- helpers

/// J87: the Python name of a hoisted UTF-16 view (`_jsu_` is neither a runtime name, which all
/// start `_js_`, `_Js` or `_JS_`, nor a source one, which may not start `_js`).
fn units_name(name: &str) -> String {
    format!("_jsu_{}", py_name(name, false, false))
}

/// J90-2: `name` appears in `code` as a whole Python identifier (as `lib.rs`'s `uses`).
fn uses_ident(code: &str, name: &str) -> bool {
    let ident = |c: char| c.is_ascii_alphanumeric() || c == '_';
    code.match_indices(name).any(|(at, _)| {
        let before = code[..at].chars().next_back();
        let after = code[at + name.len()..].chars().next();
        !before.is_some_and(ident) && !after.is_some_and(ident)
    })
}

fn method_as_value(name: &str) -> String {
    format!("method .{name} read as a value (a method may only be called directly)")
}

/// J90-P3: the lines with every compiler temporary (`_js_caught`, `_js_error`, `_js_fn`,
/// `_js_arg`, `_js_t`, `_js_first`, `_js_obj`, `_js_switch`, `_js_item` followed by digits, as a
/// whole name) renumbered in the order it first appears: two bodies that differ only in which
/// numbers their temporaries got are equal here.
fn canonical_temps(lines: &[&String]) -> Vec<String> {
    const TEMPS: [&str; 9] = [
        "caught", "error", "fn", "arg", "t", "first", "obj", "switch", "item",
    ];
    let word = |c: u8| c.is_ascii_alphanumeric() || c == b'_';
    let mut seen: HashMap<String, usize> = HashMap::new();
    let mut out = Vec::with_capacity(lines.len());
    for line in lines {
        let bytes = line.as_bytes();
        let mut text = String::with_capacity(line.len());
        let mut at = 0;
        while at < bytes.len() {
            let start_ok = at == 0 || !word(bytes[at - 1]);
            let mut taken = None;
            if start_ok && line[at..].starts_with("_js_") {
                for temp in TEMPS {
                    let rest = &line[at + 4..];
                    if let Some(digits) = rest.strip_prefix(temp) {
                        let n = digits.bytes().take_while(u8::is_ascii_digit).count();
                        let end = at + 4 + temp.len() + n;
                        if n > 0 && (end == bytes.len() || !word(bytes[end])) {
                            taken = Some(end);
                            break;
                        }
                    }
                }
            }
            match taken {
                Some(end) => {
                    let name = &line[at..end];
                    let next = seen.len();
                    let k = *seen.entry(name.to_string()).or_insert(next);
                    text.push_str(&format!("\u{0}{k}"));
                    at = end;
                }
                None => {
                    let ch = line[at..].chars().next().unwrap();
                    text.push(ch);
                    at += ch.len_utf8();
                }
            }
        }
        out.push(text);
    }
    out
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
    if let Some(fast) = f64_arith(op, &left, &right) {
        return fast;
    }
    // J91-1 (#341): two indices (each an int in `[0, 2**52]`) add to an int within 2**53 and
    // subtract to one within 2**52 of zero: the exact result is a double's exact int, so it is
    // JS's, and Python's int arithmetic is the whole lowering (no `_js_num`). Not for an
    // optimistic operand (`arith` re-marks the result optimistic, as for any other).
    if left.is_idx && right.is_idx && !left.top && !right.top {
        let (sym, prec) = match op {
            Op::Addition => ("+", ADD),
            Op::Subtraction => ("-", ADD),
            _ => ("", 0),
        };
        if !sym.is_empty() {
            return Py {
                is_num: true,
                is_double: true,
                is_int: true,
                pure: left.pure && right.pure,
                ..Py::new(
                    format!("{} {sym} {}", left.at(prec), right.at(prec + 1)),
                    prec,
                )
            };
        }
    }
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

/// J89-3: `left <op> right` for `+ - * /` when both are proven numbers and at least one is a
/// proven float. Python's float arithmetic is IEEE-754's, and an int within 2**53 (all a proven
/// number can be) converts to the double it is exactly, so `+`, `-` and `*` are the native
/// operators and the result is a float. Division is native too, except that a zero divisor
/// (`0.0`, `-0.0`, or an int 0), where Python raises ZeroDivisionError, takes `_js_div`'s answer (a
/// signed Infinity or NaN, a float either way): inline when the divisor is a name or a literal (read
/// twice; both operands are side-effect free there), else through `_js_fdiv`. `%` keeps its helper.
/// Where the general helpers spell an integral product or quotient as an int, this spells it as a
/// float: the same JS value, which every runtime helper reads either way (`+` of two floats was
/// already one, J89-2).
fn f64_arith(op: BinaryOperator, left: &Py, right: &Py) -> Option<Py> {
    use BinaryOperator as Op;
    let num = |p: &Py| p.is_num && p.is_double && !p.top;
    if !(num(left) && num(right) && (left.is_f64 || right.is_f64)) {
        return None;
    }
    let simple = |p: &Py| {
        let c = p.code.as_str();
        p.pure
            && !c.is_empty()
            && (c.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
                && !c.starts_with(|ch: char| ch.is_ascii_digit())
                || c.parse::<f64>().is_ok())
    };
    let (code, prec) = match op {
        Op::Addition => (format!("{} + {}", left.at(ADD), right.at(ADD + 1)), ADD),
        Op::Subtraction => (format!("{} - {}", left.at(ADD), right.at(ADD + 1)), ADD),
        Op::Multiplication => (format!("{} * {}", left.at(MUL), right.at(MUL + 1)), MUL),
        Op::Division => match right.code.parse::<f64>() {
            Ok(divisor) if divisor != 0.0 => {
                (format!("{} / {}", left.at(MUL), right.at(MUL + 1)), MUL)
            }
            _ if simple(right) && left.pure => (
                format!(
                    "{l} / {r} if {r} else _js_div({lc}, {r})",
                    l = left.at(MUL),
                    r = right.code,
                    lc = left.code
                ),
                TERNARY,
            ),
            _ => (format!("_js_fdiv({}, {})", left.code, right.code), ATOM),
        },
        _ => return None,
    };
    Some(Py {
        is_num: true,
        is_double: true,
        is_f64: true,
        pure: left.pure && right.pure,
        ..Py::new(code, prec)
    })
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
/// J91-1 (#341): a length (of a proven list, `len`; of a proven `str`, its UTF-16 units) is an index
/// (`types::IDX_MAX`, 2**52). A list of n items holds n pointers (8n bytes) and a `str` of n code
/// points at least n bytes, so a list past 2**52 items would need 32 PiB and a `str` past 2**51
/// code points (2**52 units) 2 PiB, in one object: the largest single-image machines address under
/// 2**47 bytes of memory (and no CPython build runs where a process can hold 2**51 bytes).
fn len_idx(value: Py) -> Py {
    Py {
        is_int: true,
        is_idx: true,
        ..value
    }
}

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
    } else if value.is_num && value.pure && !value.top && value.prec == ATOM {
        // J90-P3: a proven number named once (a name, an element read): falsy exactly when it is
        // `0`, `-0` or NaN (`x == x` is false only for NaN).
        Py::boolean(format!("{c} != 0 and {c} == {c}", c = value.code), AND)
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

/// J90-P: `(v) => Object.entries(v)` (casts allowed): one plain parameter, an expression body
/// that is exactly that call of it.
fn is_entries_alias(a: &ArrowFunctionExpression<'_>) -> bool {
    if a.params.items.len() != 1 || a.params.rest.is_some() {
        return false;
    }
    let BindingPattern::BindingIdentifier(param) = &a.params.items[0].pattern else {
        return false;
    };
    if matches!(&a.body, ArrowFunctionBody::FunctionBody(_)) {
        return false;
    }
    let Some(body) = a.body.as_expression() else {
        return false;
    };
    let Expression::CallExpression(c) = strip(body) else {
        return false;
    };
    !c.optional
        && matches!(strip(&c.callee), Expression::StaticMemberExpression(m)
            if !m.optional && m.property.name == "entries"
                && matches!(strip(&m.object), Expression::Identifier(o) if o.name == "Object"))
        && matches!(c.arguments.as_slice(), [arg]
            if matches!(arg.as_expression().map(strip), Some(Expression::Identifier(x)) if x.name == param.name))
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
/// J89-4a: JS's `\s`, every code unit `/\s/` matches (pinned against Node in `tests/g3.rs`).
const JS_SPACE_CLASS: &str = "[\\t\\n\\u000b\\u000c\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]";
/// J89-4a: JS's `\S`, the complement of `JS_SPACE_CLASS`.
const JS_NON_SPACE_CLASS: &str = "[^\\t\\n\\u000b\\u000c\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]";

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
                    // J89-4a: JS's `\s` (WhiteSpace and LineTerminator), spelled out: Python's
                    // `\s` adds U+001C-U+001F and U+0085 and leaves out U+FEFF.
                    's' => out.push_str(JS_SPACE_CLASS),
                    'S' => out.push_str(JS_NON_SPACE_CLASS),
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

/// J90-P6: `name(arg, ...)` spanning all of `code`: the name and the top-level arguments, split at
/// commas outside brackets and string literals. `None` for anything else (a call followed by more
/// code, a keyword argument, a starred argument, an unbalanced text).
fn split_call(code: &str) -> Option<(&str, Vec<String>)> {
    let open = code.find('(')?;
    let name = &code[..open];
    if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return None;
    }
    let inner = code[open + 1..].strip_suffix(')')?;
    let mut args = Vec::new();
    let mut depth = 0i32;
    let mut quote: Option<char> = None;
    let mut escaped = false;
    let mut start = 0;
    for (i, c) in inner.char_indices() {
        if let Some(q) = quote {
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == q {
                quote = None;
            }
            continue;
        }
        match c {
            '"' | '\'' => quote = Some(c),
            '(' | '[' | '{' => depth += 1,
            ')' | ']' | '}' => {
                depth -= 1;
                if depth < 0 {
                    return None;
                }
            }
            ',' if depth == 0 => {
                args.push(inner[start..i].trim().to_string());
                start = i + 1;
            }
            _ => {}
        }
    }
    if depth != 0 || quote.is_some() {
        return None;
    }
    let last = inner[start..].trim();
    if !last.is_empty() {
        args.push(last.to_string());
    }
    if args
        .iter()
        .any(|a| a.is_empty() || a.starts_with('*') || is_keyword_arg(a))
    {
        return None;
    }
    Some((name, args))
}

/// `name=value` at the top level of an argument (not `==`, `<=`, `>=`, `!=`, `:=`).
fn is_keyword_arg(arg: &str) -> bool {
    let head: String = arg
        .chars()
        .take_while(|c| c.is_ascii_alphanumeric() || *c == '_')
        .collect();
    !head.is_empty() && arg[head.len()..].starts_with('=') && !arg[head.len()..].starts_with("==")
}

/// J90-P6: an operand `hot` may read twice: a Python name (never a keyword other than the three
/// constants), an int or float literal, or a plain double-quoted string literal. Reading one runs
/// no code, so a second read gives the same value.
fn simple_operand(code: &str) -> bool {
    matches!(code, "True" | "False" | "None")
        || is_name(code)
        || is_int_literal(code)
        || is_float_literal(code)
        || is_str_literal(code)
}

/// J90-PF: a value a statement expansion may store after its guard: a `simple_operand`, or a list
/// display of them (`[row]`), whose evaluation reads names and runs no code.
fn simple_value(code: &str) -> bool {
    if simple_operand(code) {
        return true;
    }
    let Some(inner) = code.strip_prefix('[').and_then(|c| c.strip_suffix(']')) else {
        return false;
    };
    !inner.trim().is_empty()
        && !inner.contains(['[', ']', '(', ')', '"', '\''])
        && inner.split(',').all(|item| simple_operand(item.trim()))
}

/// A Python name, never a keyword.
fn is_name(code: &str) -> bool {
    let mut chars = code.chars();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
        && !is_py_keyword(code)
}

fn is_int_literal(code: &str) -> bool {
    let digits = code.strip_prefix('-').unwrap_or(code);
    !digits.is_empty() && digits.chars().all(|c| c.is_ascii_digit())
}

fn is_float_literal(code: &str) -> bool {
    let body = code.strip_prefix('-').unwrap_or(code);
    !body.is_empty()
        && body.chars().next().is_some_and(|c| c.is_ascii_digit())
        && body
            .chars()
            .all(|c| c.is_ascii_digit() || matches!(c, '.' | 'e' | 'E' | '+' | '-'))
}

/// A `py_str` literal: `"`, then no unescaped `"` until the closing one.
fn is_str_literal(code: &str) -> bool {
    let Some(body) = code.strip_prefix('"').and_then(|b| b.strip_suffix('"')) else {
        return false;
    };
    let mut escaped = false;
    for c in body.chars() {
        if escaped {
            escaped = false;
        } else if c == '\\' {
            escaped = true;
        } else if c == '"' {
            return false;
        }
    }
    !escaped
}

/// J90-P7 (#316 G4): mypyc 2.4.1 cannot compile a method of a non-native class whose body holds a
/// nested function or lambda that captures a variable (an internal error, mypyc/mypyc#1205; fixed
/// by python/mypy#22237, not in a release). Every class ts2py writes is non-native under mypyc, so a
/// method holding a `def` or a `lambda` is written as a module-level function
/// `_js_method_<Class>_<name>` right after the class, and the method forwards to it with the same
/// parameters: the same body, the same `self`, run in the same order. ts2py emits no `super()`
/// (whose `__class__` cell would not survive the move), and refuses a TypeScript name with a
/// `_js_` prefix, so the new name cannot meet one from the source. A class written inside a
/// function (indented) is left as it is.
fn hoist_closure_methods(lines: Vec<String>) -> Vec<String> {
    let Some(at) = lines.iter().position(|l| l.starts_with("class ")) else {
        return lines;
    };
    let class = lines[at]["class ".len()..]
        .split(['(', ':'])
        .next()
        .unwrap_or("")
        .to_string();
    // Split the class body into member chunks: each starts at a `    def` (with the decorator line
    // before it, when there is one).
    let mut head: Vec<String> = lines[..=at].to_vec();
    let mut chunks: Vec<Vec<String>> = Vec::new();
    let mut i = at + 1;
    while i < lines.len() {
        let line = &lines[i];
        let starts = line.starts_with("    def ")
            || (line.starts_with("    @")
                && lines.get(i + 1).is_some_and(|n| n.starts_with("    def ")));
        if starts {
            let mut chunk = vec![line.clone()];
            if line.starts_with("    @") {
                i += 1;
                chunk.push(lines[i].clone());
            }
            i += 1;
            while i < lines.len() && (lines[i].is_empty() || lines[i].starts_with("        ")) {
                chunk.push(lines[i].clone());
                i += 1;
            }
            chunks.push(chunk);
        } else if chunks.is_empty() {
            head.push(line.clone());
            i += 1;
        } else {
            // Anything else after the first member: keep the class as written.
            return lines;
        }
    }
    let nested = |chunk: &[String]| {
        chunk
            .iter()
            .skip_while(|l| !l.starts_with("    def "))
            .skip(1)
            .any(|l| {
                let t = l.trim_start();
                t.starts_with("def ") || has_word(l, "lambda")
            })
    };
    let mut body: Vec<String> = head;
    let mut after: Vec<String> = Vec::new();
    for chunk in chunks {
        if !nested(&chunk) {
            body.extend(chunk);
            continue;
        }
        let d = chunk
            .iter()
            .position(|l| l.starts_with("    def "))
            .expect("a def");
        let header = &chunk[d];
        let key = header["    def ".len()..]
            .split('(')
            .next()
            .unwrap_or("")
            .to_string();
        let open = header.find('(').expect("(");
        let close = header.rfind(')').expect(")");
        let params = &header[open + 1..close];
        let tail = &header[close..];
        let fname = format!("_js_method_{class}_{key}");
        let forward: Vec<String> = split_params(params)
            .into_iter()
            .filter(|p| *p != "*_")
            .map(|p| p.split('=').next().unwrap_or("").trim().to_string())
            .collect();
        // The method: its decorator and header as written, one forwarding line.
        body.extend(chunk[..=d].iter().cloned());
        body.push(format!("        return {fname}({})", forward.join(", ")));
        // The function: the same header under the new name, the body one level out.
        let trailing: Vec<&String> = chunk[d + 1..].iter().collect();
        let blank = trailing.iter().rev().take_while(|l| l.is_empty()).count();
        after.push(String::new());
        after.push(String::new());
        let returns = tail.trim_start_matches(')').trim_end_matches(':');
        after.push(format!("def {fname}({params}){returns}:"));
        for l in &trailing[..trailing.len() - blank] {
            after.push(if l.is_empty() {
                String::new()
            } else {
                l[4..].to_string()
            });
        }
        for _ in 0..blank {
            body.push(String::new());
        }
    }
    // Keep the blank lines that separated members in the class as the source had them.
    let mut out = body;
    while out.last().is_some_and(String::is_empty) {
        out.pop();
    }
    out.extend(after);
    out
}

/// A parameter list split at its top-level commas.
fn split_params(params: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut depth = 0i32;
    let mut from = 0;
    for (i, c) in params.char_indices() {
        match c {
            '(' | '[' | '{' => depth += 1,
            ')' | ']' | '}' => depth -= 1,
            ',' if depth == 0 => {
                out.push(params[from..i].trim());
                from = i + 1;
            }
            _ => {}
        }
    }
    if !params[from..].trim().is_empty() {
        out.push(params[from..].trim());
    }
    out
}

/// `word` appears in `line` as a whole identifier.
fn has_word(line: &str, word: &str) -> bool {
    let ident = |c: char| c.is_ascii_alphanumeric() || c == '_';
    line.match_indices(word).any(|(at, _)| {
        !line[..at].chars().next_back().is_some_and(ident)
            && !line[at + word.len()..].chars().next().is_some_and(ident)
    })
}

#[cfg(test)]
mod tests {
    use super::translate_regex;

    #[test]
    fn regex_translation() {
        assert_eq!(translate_regex("^[A-Za-z]:").unwrap(), "^[A-Za-z]:");
        assert_eq!(translate_regex("a$").unwrap(), "a\\Z");
        assert_eq!(translate_regex("\\d+").unwrap(), "[0-9]+");
        // J89-4a: `\s` is JS's set spelled out; inside a class it stays refused.
        assert_eq!(
            translate_regex("\\s").unwrap(),
            "[\\t\\n\\u000b\\u000c\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]"
        );
        assert!(translate_regex("[\\s]").is_err());
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
