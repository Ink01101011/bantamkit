//! J87 (#316): what the compiler can PROVE about a value, so a lowering may skip the JS-semantics
//! helper it would otherwise need (SUBSET.md, *Types: proven facts and the fast paths they take*).
//!
//! A fact is never taken from a TypeScript type alone: `any`, `as`, `!`, `JSON.parse` and every
//! adapter can put any value behind any annotation. Facts come from what the compiler itself
//! controls: literals, the result of an operation whose lowering fixes its Python type, every
//! assignment to a local (met over all of them), the return statements of a function (met over all
//! of them), and a parameter annotation only inside a body that is entered either from a call site
//! that proved the argument or through a guard that checked it at run time. Facts are found by a
//! greatest fixpoint over the whole module (`lib.rs` re-lowers until nothing changes), so a fact
//! that holds is one every assignment, return and call site in the final lowering re-proved.

use std::collections::{BTreeMap, BTreeSet};

use oxc_ast::ast::*;

/// What is proven about one value. Every flag is a property of the Python value itself; the type
/// flags (`str_` to `regex`) each also mean the value is neither `null` nor `undefined`.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Fact {
    /// `type(v) is str`.
    pub str_: bool,
    /// A Python `int` (not a bool) or `float` that a JS double holds exactly: `_js_num(v) is v`.
    pub num: bool,
    /// J89-3: `type(v) is float` (so also `num`): a Float64Array element, a float literal, or
    /// arithmetic with such an operand. Python's float arithmetic on it is IEEE-754's.
    pub f64: bool,
    /// `type(v) is bool`.
    pub bool_: bool,
    /// `isinstance(v, list)`: a JS array.
    pub list: bool,
    /// A compiled `re.Pattern` without the `g` flag (a regex literal).
    pub regex: bool,
    /// What `re.exec` returns: `None` or a match array, whose element 0 is the matched `str`.
    pub match_: bool,
    /// A FRESH array (an array literal, or what a function returns when every return statement
    /// returns one): its exact length and what is proven about each element. Only an expression's
    /// value carries it, never a binding, because a binding's array can be mutated later.
    pub tuple: Option<Vec<Fact>>,
    /// What every element of an array (every property value of a plain object) is: only through a
    /// frozen module constant (`lower.rs`), whose every use reads it, so nothing can mutate it.
    pub elem: Option<Box<Fact>>,
    /// The optimistic "anything" of a key no round has assigned yet, passed through unchanged
    /// (a read of such a local, a call of such a function): it meets as the identity, so a value
    /// that never got one stays optimistic until a real value is seen.
    pub top: bool,
    /// What the value is whenever it is neither `null` nor `undefined` (a value that is "a `str`
    /// or `undefined`", such as an index into a string). A guard that rules out the nullish
    /// values narrows a `const` binding to it (`lower.rs`, narrowing).
    pub nn: Option<Box<Fact>>,
    /// Proven never `None` (`null`).
    pub no_null: bool,
    /// Proven never `_JS_UNDEFINED`.
    pub no_undef: bool,
    /// The literal `null` / the value `undefined` (their `nn` is vacuous: anything).
    pub is_null: bool,
    pub is_undef: bool,
}

impl Fact {
    pub fn top() -> Fact {
        Fact {
            top: true,
            ..Fact::default()
        }
    }

    pub fn str_() -> Fact {
        Fact {
            str_: true,
            ..Fact::default()
        }
    }
    pub fn num() -> Fact {
        Fact {
            num: true,
            ..Fact::default()
        }
    }
    /// J89-3: a Python `float` (a proven number).
    pub fn f64() -> Fact {
        Fact {
            num: true,
            f64: true,
            ..Fact::default()
        }
    }
    pub fn bool_() -> Fact {
        Fact {
            bool_: true,
            ..Fact::default()
        }
    }
    pub fn list() -> Fact {
        Fact {
            list: true,
            ..Fact::default()
        }
    }

    /// "`inner` or `undefined`" (never `null`).
    pub fn or_undefined(inner: Fact) -> Fact {
        Fact {
            nn: Some(Box::new(inner)),
            no_null: true,
            ..Fact::default()
        }
    }

    fn typed_flag(&self) -> bool {
        self.str_ || self.num || self.bool_ || self.list || self.regex
    }

    /// Never `None`.
    pub fn never_null(&self) -> bool {
        self.top || self.no_null || self.typed_flag() || self.is_undef
    }

    /// Never `_JS_UNDEFINED`.
    pub fn never_undef(&self) -> bool {
        self.top || self.no_undef || self.typed_flag() || self.match_ || self.is_null
    }

    /// The type flags and contents alone, without nullability.
    fn core(&self) -> Fact {
        Fact {
            str_: self.str_,
            num: self.num,
            f64: self.f64,
            bool_: self.bool_,
            list: self.list,
            regex: self.regex,
            match_: self.match_,
            tuple: self.tuple.clone(),
            elem: self.elem.clone(),
            top: self.top,
            ..Fact::default()
        }
    }

    /// What holds whenever the value is neither `null` nor `undefined`: None when nothing does.
    /// It carries no nullability of its own (it describes a defined value).
    pub fn defined(&self) -> Option<Fact> {
        if self.top || self.is_null || self.is_undef {
            return Some(Fact::top());
        }
        let core = match &self.nn {
            Some(nn) => nn.core(),
            None => self.core(),
        };
        (!core.is_unknown()).then_some(core)
    }

    /// `meet_core` for the lowering (two narrowings of one binding, either of which holds).
    pub fn meet_core_pub(&self, other: &Fact) -> Fact {
        self.meet_core(other)
    }

    /// `meet` of two cores (no nullability to recompute, so no recursion but into contents).
    fn meet_core(&self, other: &Fact) -> Fact {
        if self.top {
            return other.clone();
        }
        if other.top {
            return self.clone();
        }
        Fact {
            str_: self.str_ && other.str_,
            num: self.num && other.num,
            f64: self.f64 && other.f64,
            bool_: self.bool_ && other.bool_,
            list: self.list && other.list,
            regex: self.regex && other.regex,
            match_: self.match_ && other.match_,
            tuple: match (&self.tuple, &other.tuple) {
                (Some(a), Some(b)) if a.len() == b.len() => {
                    Some(a.iter().zip(b).map(|(x, y)| x.meet(y)).collect())
                }
                _ => None,
            },
            elem: match (&self.elem, &other.elem) {
                (Some(a), Some(b)) => Some(Box::new(a.meet(b))),
                _ => None,
            },
            ..Fact::default()
        }
    }

    /// What holds for a value that is one of `self` or `other`.
    pub fn meet(&self, other: &Fact) -> Fact {
        if self.top {
            return other.clone();
        }
        if other.top {
            return self.clone();
        }
        let matchish = |f: &Fact| f.match_ || f.is_null;
        let nn = match (self.defined(), other.defined()) {
            (Some(a), Some(b)) => {
                let both = a.meet_core(&b);
                (!both.is_unknown() && !both.top).then(|| Box::new(both))
            }
            _ => None,
        };
        Fact {
            str_: self.str_ && other.str_,
            num: self.num && other.num,
            f64: self.f64 && other.f64,
            bool_: self.bool_ && other.bool_,
            list: self.list && other.list,
            regex: self.regex && other.regex,
            match_: matchish(self) && matchish(other) && !(self.is_null && other.is_null),
            tuple: match (&self.tuple, &other.tuple) {
                (Some(a), Some(b)) if a.len() == b.len() => {
                    Some(a.iter().zip(b).map(|(x, y)| x.meet(y)).collect())
                }
                _ => None,
            },
            elem: match (&self.elem, &other.elem) {
                (Some(a), Some(b)) => Some(Box::new(a.meet(b))),
                _ => None,
            },
            top: false,
            nn,
            no_null: self.never_null() && other.never_null(),
            no_undef: self.never_undef() && other.never_undef(),
            is_null: self.is_null && other.is_null,
            is_undef: self.is_undef && other.is_undef,
        }
    }

    /// Every flag `need` sets, `self` sets too (a call site's argument against a parameter).
    pub fn covers(&self, need: &Fact) -> bool {
        self.top
            || (!need.str_ || self.str_)
                && (!need.num || self.num)
                && (!need.f64 || self.f64)
                && (!need.bool_ || self.bool_)
                && (!need.list || self.list)
                && (!need.regex || self.regex)
    }

    /// What a BINDING may keep of a value: no array contents, here or in what it is when defined
    /// (the array may be mutated after the binding is made).
    pub fn shallow(&self) -> Fact {
        Fact {
            tuple: None,
            elem: None,
            nn: self.nn.as_ref().map(|nn| Box::new(nn.shallow())),
            ..self.clone()
        }
    }

    /// Nothing proven.
    pub fn is_unknown(&self) -> bool {
        *self == Fact::default()
    }
}

/// The key a fact is recorded under, across the fixpoint's rounds.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Key {
    /// A local (or parameter) of the function whose scope opens at `owner` (a span start), in the
    /// typed or the guarded/untyped body of its module function; or a module-level `const`
    /// (`owner == MODULE`).
    Var {
        typed: bool,
        owner: u32,
        name: String,
        /// J89-3: 0, or the span start of the counted loop whose proven copy (`lower.rs`,
        /// `fast_loop`) declares this binding: the copy's facts are kept apart from the loop's.
        ver: u32,
    },
    /// What a module function returns, from its typed or its untyped body.
    Ret { name: String, typed: bool },
}

/// The `owner` of a module-level binding.
pub const MODULE: u32 = u32::MAX;

/// One round's assumptions. A key that is absent is optimistic (anything): the first round starts
/// there, and every later round can only take facts away and add wrappers and escapes.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Assume {
    pub facts: BTreeMap<Key, Fact>,
    /// Module functions that need the guarded entry (exported, used as a value, or called with an
    /// argument a call site could not prove).
    pub wrapped: BTreeSet<String>,
    /// Module array constants that some use could mutate, so their elements prove nothing.
    pub escaped: BTreeSet<String>,
    /// Bindings whose UTF-16 view is computed once, beside the binding, and indexed inline: a
    /// parameter or declared local proven a `str`, never assigned again, that is indexed or has its
    /// `.length` read (`lower.rs`, `units_of`).
    pub hoist: BTreeSet<Key>,
    /// `const` locals read somewhere other than a literal index, a nullish test or a truthiness
    /// test: their array contents prove nothing (`lower.rs`, `peek`).
    pub escaped_locals: BTreeSet<Key>,
}

/// What one round observed, folded into the next round's assumptions.
#[derive(Default)]
pub struct Observed {
    pub seen: BTreeMap<Key, Fact>,
    pub read: BTreeSet<Key>,
    pub wrapped: BTreeSet<String>,
    pub escaped: BTreeSet<String>,
    /// Parameters and declared locals (a binding made once per execution of its declaration).
    pub declared: BTreeSet<Key>,
    /// Bindings an assignment rebinds.
    pub assigned: BTreeSet<Key>,
    /// Bindings proven a `str` that are indexed or have their `.length` read.
    pub unit_reads: BTreeSet<Key>,
    pub escaped_locals: BTreeSet<Key>,
}

impl Observed {
    pub fn observe(&mut self, key: Key, fact: Fact) {
        match self.seen.get_mut(&key) {
            Some(old) => *old = old.meet(&fact),
            None => {
                self.seen.insert(key, fact);
            }
        }
    }

    /// The next round: every key read, seen or assumed before, met with what this round saw. A
    /// local read but never bound this round proves nothing: every binding form records one, so a
    /// form this file forgot fails safe. A function's return that no round has seen stays
    /// optimistic: its only producers are `return` statements and falling off the end (both
    /// recorded), so a function none of whose returns was seen never returns a value at all (it
    /// always throws, or its typed body is not emitted yet because it was not wrapped until now).
    pub fn next(&self, assume: &Assume) -> Assume {
        let mut keys: BTreeSet<&Key> = self
            .read
            .iter()
            .filter(|key| matches!(key, Key::Var { .. }))
            .collect();
        keys.extend(self.seen.keys());
        keys.extend(assume.facts.keys());
        let mut facts = BTreeMap::new();
        for key in keys {
            let seen = self.seen.get(key).cloned().unwrap_or_default();
            let fact = match assume.facts.get(key) {
                Some(old) => old.meet(&seen),
                None => seen,
            };
            // Still optimistic: kept absent, as it started.
            if !fact.top {
                facts.insert(key.clone(), fact);
            }
        }
        let mut wrapped = assume.wrapped.clone();
        wrapped.extend(self.wrapped.iter().cloned());
        let mut escaped = assume.escaped.clone();
        escaped.extend(self.escaped.iter().cloned());
        let hoist = self
            .declared
            .iter()
            .filter(|key| {
                facts.get(*key).is_some_and(|f| f.str_)
                    && !self.assigned.contains(*key)
                    && self.unit_reads.contains(*key)
            })
            .cloned()
            .collect();
        let mut escaped_locals = assume.escaped_locals.clone();
        escaped_locals.extend(self.escaped_locals.iter().cloned());
        Assume {
            facts,
            wrapped,
            escaped,
            hoist,
            escaped_locals,
        }
    }
}

/// Type declarations of one module, read before anything is lowered: what each interface or
/// type alias name proves (J87).
#[derive(Default)]
pub struct TypeDecls {
    /// The data fields a named object type declares (property signatures whose type is data, not a
    /// function), for interfaces and aliases of a type literal.
    pub fields: BTreeMap<String, BTreeSet<String>>,
    /// The fact a type alias of a primitive or literal union gives a guarded parameter.
    pub facts: BTreeMap<String, Fact>,
    /// Names whose type is data-shaped (never callable).
    pub data: BTreeSet<String>,
}

impl TypeDecls {
    pub fn read(program: &Program<'_>) -> TypeDecls {
        let mut aliases: BTreeMap<String, &TSType<'_>> = BTreeMap::new();
        let mut interfaces: BTreeMap<String, &TSInterfaceDeclaration<'_>> = BTreeMap::new();
        for stmt in &program.body {
            let decl = match stmt {
                Statement::ExportDeclaration(e) => Some(&e.declaration),
                _ => stmt.as_declaration(),
            };
            match decl {
                Some(Declaration::TSTypeAliasDeclaration(a)) if a.type_parameters.is_none() => {
                    aliases.insert(a.id.name.to_string(), &a.type_annotation);
                }
                Some(Declaration::TSInterfaceDeclaration(i)) if i.type_parameters.is_none() => {
                    interfaces.insert(i.id.name.to_string(), i);
                }
                _ => {}
            }
        }
        let env = Env {
            aliases: &aliases,
            interfaces: &interfaces,
        };
        let mut out = TypeDecls::default();
        for (name, t) in &aliases {
            if let Some(fields) = env.fields_of(t, 0) {
                out.fields.insert(name.clone(), fields);
            }
            if let Some(fact) = env.fact_of(t, 0) {
                out.facts.insert(name.clone(), fact);
            }
            if env.is_data(t, 0) {
                out.data.insert(name.clone());
            }
        }
        for (name, i) in &interfaces {
            if let Some(fields) = env.signatures(&i.body.body, 0) {
                out.fields.insert(name.clone(), fields);
                out.data.insert(name.clone());
            }
        }
        out
    }

    /// The fact a parameter annotated `t` holds once a guard (or a proving call site) admitted it.
    pub fn param_fact(&self, t: &TSType<'_>) -> Option<Fact> {
        let empty_a = BTreeMap::new();
        let empty_i = BTreeMap::new();
        let env = Env {
            aliases: &empty_a,
            interfaces: &empty_i,
        };
        match t {
            TSType::TSTypeReference(r) => match &r.type_name {
                TSTypeName::IdentifierReference(id) if r.type_arguments.is_none() => {
                    self.facts.get(id.name.as_str()).cloned()
                }
                _ => env.fact_of(t, 0),
            },
            _ => env.fact_of(t, 0),
        }
    }

    /// The data fields an annotation declares (`{ get: number }`, an interface, an alias of one).
    pub fn annotation_fields(&self, t: &TSType<'_>) -> Option<BTreeSet<String>> {
        match t {
            TSType::TSTypeLiteral(l) => self.literal_fields(&l.members),
            TSType::TSTypeReference(r) if r.type_arguments.is_none() => match &r.type_name {
                TSTypeName::IdentifierReference(id) => self.fields.get(id.name.as_str()).cloned(),
                _ => None,
            },
            _ => None,
        }
    }

    fn literal_fields(&self, members: &[TSSignature<'_>]) -> Option<BTreeSet<String>> {
        let mut fields = BTreeSet::new();
        for member in members {
            match member {
                TSSignature::TSPropertySignature(p) if !p.computed => {
                    let Some(name) = signature_key(&p.key) else {
                        continue;
                    };
                    let data = p
                        .type_annotation
                        .as_ref()
                        .is_some_and(|a| self.shallow_data(&a.type_annotation));
                    if data {
                        fields.insert(name);
                    }
                }
                TSSignature::TSPropertySignature(_) | TSSignature::TSMethodSignature(_) => {}
                // A callable object type (`{ (): void }`) is a function, not an object of fields.
                _ => return None,
            }
        }
        Some(fields)
    }

    /// `shallow_data` with the module's named types already read (for a local `{...}` literal).
    fn shallow_data(&self, t: &TSType<'_>) -> bool {
        match t {
            TSType::TSTypeReference(r) if r.type_arguments.is_none() => match &r.type_name {
                TSTypeName::IdentifierReference(id) => self.data.contains(id.name.as_str()),
                _ => false,
            },
            TSType::TSUnionType(u) => u.types.iter().all(|t| self.shallow_data(t)),
            TSType::TSTypeLiteral(l) => self.literal_fields(&l.members).is_some(),
            other => {
                let empty_a = BTreeMap::new();
                let empty_i = BTreeMap::new();
                Env {
                    aliases: &empty_a,
                    interfaces: &empty_i,
                }
                .is_data(other, 0)
            }
        }
    }
}

struct Env<'e, 'a> {
    aliases: &'e BTreeMap<String, &'e TSType<'a>>,
    interfaces: &'e BTreeMap<String, &'e TSInterfaceDeclaration<'a>>,
}

/// How deep a chain of aliases is followed before giving up (a cycle proves nothing).
const DEPTH: usize = 16;

impl Env<'_, '_> {
    /// The single fact every value of `t` has, if one does: `string` and string literal types
    /// give `str`, `number` and numeric literals `num`, `boolean` and its literals `bool`, any
    /// array or tuple type `list`; a union whose members all give one flag gives it.
    fn fact_of(&self, t: &TSType<'_>, depth: usize) -> Option<Fact> {
        if depth > DEPTH {
            return None;
        }
        match t {
            TSType::TSStringKeyword(_) => Some(Fact::str_()),
            TSType::TSNumberKeyword(_) => Some(Fact::num()),
            TSType::TSBooleanKeyword(_) => Some(Fact::bool_()),
            TSType::TSArrayType(_) | TSType::TSTupleType(_) => Some(Fact::list()),
            TSType::TSTypeOperatorType(o) if o.operator == TSTypeOperatorOperator::Readonly => {
                match &o.type_annotation {
                    TSType::TSArrayType(_) | TSType::TSTupleType(_) => Some(Fact::list()),
                    _ => None,
                }
            }
            TSType::TSLiteralType(l) => match &l.literal {
                TSLiteral::StringLiteral(_) | TSLiteral::TemplateLiteral(_) => Some(Fact::str_()),
                // A numeric literal type admits only that finite number; `-1` is a unary minus.
                TSLiteral::NumericLiteral(_) | TSLiteral::UnaryExpression(_) => Some(Fact::num()),
                TSLiteral::BooleanLiteral(_) => Some(Fact::bool_()),
                TSLiteral::BigIntLiteral(_) => None,
            },
            TSType::TSUnionType(u) => {
                let mut facts = u.types.iter().map(|t| self.fact_of(t, depth + 1));
                let first = facts.next()??;
                for fact in facts {
                    if fact? != first {
                        return None;
                    }
                }
                Some(first)
            }
            TSType::TSParenthesizedType(p) => self.fact_of(&p.type_annotation, depth + 1),
            TSType::TSTypeReference(r) => match &r.type_name {
                TSTypeName::IdentifierReference(id) => {
                    let name = id.name.as_str();
                    if matches!(name, "Array" | "ReadonlyArray") && r.type_arguments.is_some() {
                        return Some(Fact::list());
                    }
                    if r.type_arguments.is_some() {
                        return None;
                    }
                    self.aliases
                        .get(name)
                        .and_then(|t| self.fact_of(t, depth + 1))
                }
                _ => None,
            },
            _ => None,
        }
    }

    /// `t` never admits a function: reading a member of this type is reading data.
    fn is_data(&self, t: &TSType<'_>, depth: usize) -> bool {
        if depth > DEPTH {
            return false;
        }
        match t {
            TSType::TSStringKeyword(_)
            | TSType::TSNumberKeyword(_)
            | TSType::TSBooleanKeyword(_)
            | TSType::TSBigIntKeyword(_)
            | TSType::TSNullKeyword(_)
            | TSType::TSUndefinedKeyword(_)
            | TSType::TSLiteralType(_)
            | TSType::TSArrayType(_)
            | TSType::TSTupleType(_) => true,
            TSType::TSTypeOperatorType(o) => {
                o.operator == TSTypeOperatorOperator::Readonly
                    && self.is_data(&o.type_annotation, depth + 1)
            }
            TSType::TSParenthesizedType(p) => self.is_data(&p.type_annotation, depth + 1),
            TSType::TSUnionType(u) => u.types.iter().all(|t| self.is_data(t, depth + 1)),
            TSType::TSTypeLiteral(l) => self.signatures(&l.members, depth + 1).is_some(),
            TSType::TSTypeReference(r) => match &r.type_name {
                TSTypeName::IdentifierReference(id) => {
                    let name = id.name.as_str();
                    if r.type_arguments.is_some() {
                        // Containers whose values are objects, never callables.
                        return matches!(
                            name,
                            "Array"
                                | "ReadonlyArray"
                                | "Record"
                                | "Map"
                                | "Set"
                                | "ReadonlyMap"
                                | "ReadonlySet"
                        );
                    }
                    if let Some(t) = self.aliases.get(name) {
                        return self.is_data(t, depth + 1);
                    }
                    self.interfaces
                        .get(name)
                        .is_some_and(|i| self.signatures(&i.body.body, depth + 1).is_some())
                }
                _ => false,
            },
            _ => false,
        }
    }

    /// The data fields of an object type's members, or None when the type is callable.
    fn signatures(&self, members: &[TSSignature<'_>], depth: usize) -> Option<BTreeSet<String>> {
        let mut fields = BTreeSet::new();
        for member in members {
            match member {
                TSSignature::TSPropertySignature(p) if !p.computed => {
                    let Some(name) = signature_key(&p.key) else {
                        continue;
                    };
                    let data = p
                        .type_annotation
                        .as_ref()
                        .is_some_and(|a| self.is_data(&a.type_annotation, depth + 1));
                    if data {
                        fields.insert(name);
                    }
                }
                TSSignature::TSPropertySignature(_)
                | TSSignature::TSMethodSignature(_)
                | TSSignature::TSIndexSignature(_) => {}
                _ => return None,
            }
        }
        Some(fields)
    }

    fn fields_of(&self, t: &TSType<'_>, depth: usize) -> Option<BTreeSet<String>> {
        if depth > DEPTH {
            return None;
        }
        match t {
            TSType::TSTypeLiteral(l) => self.signatures(&l.members, depth + 1),
            TSType::TSTypeReference(r) if r.type_arguments.is_none() => match &r.type_name {
                TSTypeName::IdentifierReference(id) => {
                    let name = id.name.as_str();
                    if let Some(t) = self.aliases.get(name) {
                        return self.fields_of(t, depth + 1);
                    }
                    self.interfaces
                        .get(name)
                        .and_then(|i| self.signatures(&i.body.body, depth + 1))
                }
                _ => None,
            },
            _ => None,
        }
    }
}

fn signature_key(key: &PropertyKey<'_>) -> Option<String> {
    match key {
        PropertyKey::StaticIdentifier(id) => Some(id.name.to_string()),
        PropertyKey::StringLiteral(s) => s.value.as_str().map(str::to_string),
        _ => None,
    }
}

/// The Python test a guard uses to admit a value with `fact` (one flag, from an annotation).
pub fn guard_test(fact: &Fact, name: &str) -> String {
    if fact.str_ {
        format!("type({name}) is str")
    } else if fact.num {
        format!("_js_is_double({name})")
    } else if fact.bool_ {
        format!("type({name}) is bool")
    } else {
        format!("type({name}) is list")
    }
}

/// Control can reach the end of `stmts` (so a function falls off it and returns `undefined`): it
/// does unless the last statement exits or is a `for (;;)` / `while (true)` no `break` leaves.
pub fn completes(stmts: &[Statement<'_>]) -> bool {
    match stmts.last() {
        None => true,
        Some(last) => !(crate::lower::exits_pub(last) || endless(last)),
    }
}

fn endless(s: &Statement<'_>) -> bool {
    let body = match s {
        Statement::ForStatement(f)
            if f.init.is_none() && f.test.is_none() && f.update.is_none() =>
        {
            &f.body
        }
        Statement::WhileStatement(w) if matches!(&w.test, Expression::BooleanLiteral(b) if b.value) => {
            &w.body
        }
        Statement::BlockStatement(b) => {
            return b.body.last().is_some_and(endless);
        }
        _ => return false,
    };
    !breaks_out(body)
}

/// A `break` in `s` that leaves the loop `s` is the body of (not one inside a nested loop, nor
/// the trailing `break` of a `switch` case, which leaves the switch).
fn breaks_out(s: &Statement<'_>) -> bool {
    match s {
        Statement::BreakStatement(_) => true,
        Statement::BlockStatement(b) => b.body.iter().any(breaks_out),
        Statement::IfStatement(i) => {
            breaks_out(&i.consequent) || i.alternate.as_ref().is_some_and(breaks_out)
        }
        Statement::LabeledStatement(_) => true,
        // J87-3.
        Statement::TryStatement(t) => {
            t.block.body.iter().any(breaks_out)
                || t.handler
                    .as_ref()
                    .is_some_and(|h| h.body.body.iter().any(breaks_out))
        }
        Statement::SwitchStatement(sw) => sw.cases.iter().any(|case| {
            let body = match case.consequent.last() {
                Some(Statement::BreakStatement(b)) if b.label.is_none() => {
                    &case.consequent[..case.consequent.len() - 1]
                }
                _ => &case.consequent[..],
            };
            body.iter().any(breaks_out)
        }),
        _ => false,
    }
}
