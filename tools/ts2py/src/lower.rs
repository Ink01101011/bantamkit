//! TypeScript AST (oxc) to Python source, for the subset `SUBSET.md` lists.
//!
//! Every construct outside the subset is refused with a span and a construct name; lowering keeps
//! going after a refusal so one run reports every offence, and the caller writes nothing when any
//! refusal was recorded.

use std::collections::{HashMap, HashSet};

use oxc_ast::ast::*;
use oxc_span::{GetSpan, Span};

use crate::pyfmt::{py_name, py_number, py_str, py_str_utf16};

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
    fn at(&self, min: u8) -> String {
        if self.prec < min {
            format!("({})", self.code)
        } else {
            self.code.clone()
        }
    }
}

/// Methods the subset accepts, with the argument counts each takes and which argument (if any)
/// is a callback that must be an inline arrow.
const METHODS: &[(&str, usize, usize, Option<usize>, bool)] = &[
    // name, min args, max args, callback index, returns bool
    ("has", 1, 1, None, true),
    ("get", 1, 1, None, false),
    ("set", 2, 2, None, false),
    ("add", 1, 1, None, false),
    ("includes", 1, 1, None, true),
    ("startsWith", 1, 1, None, true),
    ("split", 1, 1, None, false),
    ("test", 1, 1, None, true),
    ("every", 1, 1, Some(0), true),
    ("some", 1, 1, Some(0), true),
    ("find", 1, 1, Some(0), false),
    ("map", 1, 1, Some(0), false),
    ("push", 1, usize::MAX, None, false),
    ("slice", 0, 2, None, false),
    ("join", 0, 1, None, false),
    ("sort", 0, 1, Some(0), false),
    ("entries", 0, 0, None, false),
];

pub struct Lowerer<'s> {
    src: &'s str,
    pub refusals: Vec<Refusal>,
    /// Hoisted regex constants: translated pattern, in first-use order.
    regexes: Vec<String>,
    /// Module-level source name -> Python name.
    globals: HashMap<String, String>,
    /// Module-level functions annotated `: boolean`.
    bool_fns: HashSet<String>,
    /// Python names of exported bindings.
    pub exports: Vec<String>,
    /// Local scopes, innermost last: a function's locals, then each enclosing lambda's params.
    scopes: Vec<HashSet<String>>,
    /// Python name -> the source name that claimed it, so two names never fold into one.
    owners: HashMap<String, String>,
    tmp: usize,
}

impl<'s> Lowerer<'s> {
    pub fn new(src: &'s str) -> Self {
        Lowerer {
            src,
            refusals: Vec::new(),
            regexes: Vec::new(),
            globals: HashMap::new(),
            bool_fns: HashSet::new(),
            exports: Vec::new(),
            scopes: Vec::new(),
            owners: HashMap::new(),
            tmp: 0,
        }
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
        // Pass 1: module-level names, so a function may call one declared below it.
        for stmt in &program.body {
            let (decl, exported) = match stmt {
                Statement::ExportDeclaration(e) => (Some(&e.declaration), true),
                _ => (stmt.as_declaration(), false),
            };
            let Some(decl) = decl else { continue };
            match decl {
                Declaration::FunctionDeclaration(f) => {
                    if let Some(id) = &f.id {
                        self.declare_global(id.name.as_str(), exported, id.span);
                        if returns_boolean(f.return_type.as_deref()) {
                            self.bool_fns.insert(id.name.to_string());
                        }
                    }
                }
                Declaration::VariableDeclaration(v) => {
                    for d in &v.declarations {
                        if let BindingPattern::BindingIdentifier(id) = &d.id {
                            self.declare_global(id.name.as_str(), exported, id.span);
                            if let Some(Expression::ArrowFunctionExpression(a)) = &d.init
                                && returns_boolean(a.return_type.as_deref())
                            {
                                self.bool_fns.insert(id.name.to_string());
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
            for (i, pattern) in self.regexes.iter().enumerate() {
                body.push_str(&format!(
                    "_JS_RE_{i} = _js_re.compile({}, _js_re.ASCII)\n",
                    py_str(pattern)
                ));
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
                    self.refuse(e.span, "export list");
                }
            }
            Statement::ExportFromDeclaration(e) => {
                if !e.export_kind.is_type() {
                    self.refuse(e.span, "re-export");
                }
            }
            Statement::ImportDeclaration(i) => {
                if !i.import_kind.is_type() {
                    self.refuse(i.span, "import");
                }
            }
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
                let name = self.globals[id.name.as_str()].clone();
                match &f.body {
                    Some(body) => self.function(&name, f, &f.params, &body.statements, out),
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
                            self.arrow_function(&name, a, out);
                        }
                        Some(init) => {
                            let value = self.expr(init);
                            out.push(format!("{name} = {}", value.code));
                        }
                        None => {
                            self.refuse(d.span, "const without initializer");
                        }
                    }
                }
            }
            Declaration::ClassDeclaration(c) => {
                self.refuse(c.span, "class");
            }
            Declaration::TSEnumDeclaration(e) => {
                self.refuse(e.span, "enum");
            }
            other => {
                self.refuse(other.span(), "declaration");
            }
        }
    }

    // ---------------------------------------------------------------- functions

    fn function(
        &mut self,
        name: &str,
        f: &Function<'_>,
        params: &FormalParameters<'_>,
        body: &[Statement<'_>],
        out: &mut Vec<String>,
    ) {
        if f.generator {
            self.refuse(f.span, "generator function");
        }
        if f.r#async {
            self.refuse(f.span, "async function");
        }
        let names = self.params(params);
        let mut locals: HashSet<String> = names.iter().map(|(src, _)| src.clone()).collect();
        let mut stack = vec![locals.clone()];
        self.collect_block(body, &mut stack, &mut locals);
        self.scopes.push(locals);
        out.push(format!("def {name}({}):", join_params(&names)));
        let start = out.len();
        self.block(body, 1, out);
        if out.len() == start {
            out.push("    pass".to_string());
        }
        self.scopes.pop();
    }

    /// A module-level `const f = (...) => ...` becomes `def f(...)`.
    fn arrow_function(
        &mut self,
        name: &str,
        a: &ArrowFunctionExpression<'_>,
        out: &mut Vec<String>,
    ) {
        if a.r#async {
            self.refuse(a.span, "async function");
        }
        let names = self.params(&a.params);
        let mut locals: HashSet<String> = names.iter().map(|(src, _)| src.clone()).collect();
        out.push(format!("def {name}({}):", join_params(&names)));
        match &a.body {
            ArrowFunctionBody::FunctionBody(body) => {
                let mut stack = vec![locals.clone()];
                self.collect_block(&body.statements, &mut stack, &mut locals);
                self.scopes.push(locals);
                let start = out.len();
                self.block(&body.statements, 1, out);
                if out.len() == start {
                    out.push("    pass".to_string());
                }
            }
            other => {
                self.scopes.push(locals);
                let expr = other
                    .as_expression()
                    .expect("an arrow body is a block or an expression");
                let value = self.expr(expr);
                out.push(format!("    return {}", value.code));
            }
        }
        self.scopes.pop();
    }

    /// Parameter list: `(source name, python spelling)`. An optional parameter defaults to
    /// `undefined`, which is what JS passes for a missing argument.
    fn params(&mut self, params: &FormalParameters<'_>) -> Vec<(String, String)> {
        let mut names = Vec::new();
        for p in &params.items {
            if p.initializer.is_some() {
                self.refuse(p.span, "default parameter");
            }
            let BindingPattern::BindingIdentifier(id) = &p.pattern else {
                self.refuse(p.span, "destructuring parameter");
                continue;
            };
            let py = py_name(id.name.as_str(), false, false);
            self.claim(id.name.as_str(), &py, id.span);
            let spelled = if p.optional {
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
            // Refused where the declaration is lowered.
            _ => {}
        }
    }

    fn resolve(&mut self, name: &str, span: Span) -> Py {
        if self.scopes.iter().rev().any(|scope| scope.contains(name)) {
            return Py {
                pure: true,
                ..Py::atom(py_name(name, false, false))
            };
        }
        if let Some(py) = self.globals.get(name) {
            return Py {
                pure: true,
                ..Py::atom(py.clone())
            };
        }
        if name == "undefined" {
            return Py {
                pure: true,
                ..Py::atom("_JS_UNDEFINED")
            };
        }
        let construct = format!("global {name}");
        self.refuse(span, construct)
    }

    fn is_local(&self, name: &str) -> bool {
        self.scopes.iter().any(|scope| scope.contains(name)) || self.globals.contains_key(name)
    }

    // ---------------------------------------------------------------- statements

    fn block(&mut self, stmts: &[Statement<'_>], indent: usize, out: &mut Vec<String>) {
        for s in stmts {
            self.stmt(s, indent, out);
        }
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
                    let value = self.expr(other);
                    out.push(format!("{p}{}", value.code));
                }
            },
            Statement::VariableDeclaration(v) => {
                if v.kind == VariableDeclarationKind::Var {
                    self.refuse(v.span, "var declaration");
                } else if !matches!(
                    v.kind,
                    VariableDeclarationKind::Let | VariableDeclarationKind::Const
                ) {
                    self.refuse(v.span, "using declaration");
                }
                for d in &v.declarations {
                    let BindingPattern::BindingIdentifier(id) = &d.id else {
                        self.refuse(d.span, "destructuring declaration");
                        continue;
                    };
                    let name = py_name(id.name.as_str(), false, false);
                    let value = match &d.init {
                        Some(init) => self.expr(init).code,
                        None => "_JS_UNDEFINED".to_string(),
                    };
                    out.push(format!("{p}{name} = {value}"));
                }
            }
            Statement::ReturnStatement(r) => match &r.argument {
                Some(arg) => {
                    let value = self.expr(arg);
                    out.push(format!("{p}return {}", value.code));
                }
                None => out.push(format!("{p}return _JS_UNDEFINED")),
            },
            Statement::IfStatement(i) => {
                let test = self.condition(&i.test);
                out.push(format!("{p}if {test}:"));
                self.body(&i.consequent, indent + 1, out);
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
                self.body(&w.body, indent + 1, out);
            }
            Statement::ForOfStatement(f) => self.for_of(f, indent, out),
            Statement::BlockStatement(b) => self.block(&b.body, indent, out),
            Statement::BreakStatement(b) => {
                if b.label.is_some() {
                    self.refuse(b.span, "labelled break");
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

    fn assignment(&mut self, a: &AssignmentExpression<'_>, indent: usize, out: &mut Vec<String>) {
        let p = pad(indent);
        if a.operator != AssignmentOperator::Assign {
            self.refuse(a.span, "compound assignment");
            return;
        }
        let value = self.expr(&a.right);
        match &a.left {
            AssignmentTarget::AssignmentTargetIdentifier(id) => {
                let target = self.resolve(id.name.as_str(), id.span);
                out.push(format!("{p}{} = {}", target.code, value.code));
            }
            AssignmentTarget::StaticMemberExpression(m) => {
                let object = self.expr(&m.object);
                out.push(format!(
                    "{p}_js_put({}, {}, {})",
                    object.code,
                    py_str(m.property.name.as_str()),
                    value.code
                ));
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
        let right = self.expr(&f.right);
        match &v.declarations[0].id {
            BindingPattern::BindingIdentifier(id) => {
                let name = py_name(id.name.as_str(), false, false);
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
                if names.len() == 2 && is_entries_call(&f.right) {
                    // `.entries()` yields `[index, item]` pairs, so a plain unpack is exact.
                    out.push(format!(
                        "{p}for {}, {} in {}:",
                        names[0], names[1], right.code
                    ));
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
        self.body(&f.body, indent + 1, out);
    }

    /// An expression in a condition slot: a Python bool, through `_js_truthy` unless it already is.
    fn condition(&mut self, e: &Expression<'_>) -> String {
        let value = self.expr(e);
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
            Expression::StringLiteral(s) => Py {
                is_str: true,
                pure: true,
                ..Py::atom(py_str_utf16(s.value.encode_utf16()))
            },
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
                Py {
                    is_bool: yes.is_bool && no.is_bool,
                    is_num: yes.is_num && no.is_num,
                    is_double: yes.is_double && no.is_double,
                    is_str: yes.is_str && no.is_str,
                    ..Py::new(
                        format!("{} if {} else {}", yes.at(OR), test.at(OR), no.at(TERNARY)),
                        TERNARY,
                    )
                }
            }
            Expression::CallExpression(c) => self.call(c),
            Expression::NewExpression(n) => self.new_expr(n),
            Expression::StaticMemberExpression(m) => {
                if m.optional {
                    return self.refuse(m.span, "optional chaining");
                }
                let object = self.expr(&m.object);
                match m.property.name.as_str() {
                    // A known number only on a known string: on any other receiver `.length` is
                    // whatever the object holds (`{length: '1'}`), so it is compared, added and
                    // equated through the runtime, as any unknown value is (J85-R2 L1).
                    "length" if object.is_str => Py {
                        is_num: true,
                        is_double: true,
                        ..Py::atom(format!("_js_len({})", object.code))
                    },
                    "length" => Py::atom(format!("_js_len({})", object.code)),
                    "size" => Py::atom(format!("_js_size({})", object.code)),
                    prop => Py::atom(format!("_js_get({}, {})", object.code, py_str(prop))),
                }
            }
            Expression::ComputedMemberExpression(m) => {
                if m.optional {
                    return self.refuse(m.span, "optional chaining");
                }
                let object = self.expr(&m.object);
                let key = self.expr(&m.expression);
                Py::atom(format!("_js_get({}, {})", object.code, key.code))
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
            Expression::ThisExpression(t) => self.refuse(t.span, "this"),
            Expression::AwaitExpression(a) => self.refuse(a.span, "await"),
            Expression::YieldExpression(y) => self.refuse(y.span, "yield"),
            Expression::ClassExpression(c) => self.refuse(c.span, "class"),
            Expression::FunctionExpression(f) => self.refuse(f.span, "function expression"),
            Expression::AssignmentExpression(a) => {
                self.refuse(a.span, "assignment inside an expression")
            }
            Expression::UpdateExpression(u) => self.refuse(u.span, "update expression (++/--)"),
            Expression::ChainExpression(c) => self.refuse(c.span, "optional chaining"),
            Expression::SequenceExpression(s) => self.refuse(s.span, "comma operator"),
            Expression::TaggedTemplateExpression(t) => self.refuse(t.span, "tagged template"),
            Expression::BigIntLiteral(b) => self.refuse(b.span, "bigint literal"),
            other => self.refuse(other.span(), "expression"),
        }
    }

    fn template(&mut self, t: &TemplateLiteral<'_>) -> Py {
        let mut parts: Vec<String> = Vec::new();
        for (i, quasi) in t.quasis.iter().enumerate() {
            match quasi.value.cooked {
                Some(cooked) => {
                    if cooked.len_utf16() > 0 {
                        parts.push(py_str_utf16(cooked.encode_utf16()));
                    }
                }
                None => {
                    return self.refuse(quasi.span, "template escape");
                }
            }
            if let Some(e) = t.expressions.get(i) {
                let value = self.expr(e);
                parts.push(if value.is_str {
                    value.at(ADD + 1)
                } else {
                    format!("_js_str({})", value.code)
                });
            }
        }
        match parts.len() {
            0 => Py {
                is_str: true,
                pure: true,
                ..Py::atom("\"\"")
            },
            1 => Py {
                is_str: true,
                ..Py::atom(parts.remove(0))
            },
            _ => Py {
                is_str: true,
                ..Py::new(parts.join(" + "), ADD)
            },
        }
    }

    fn array(&mut self, a: &ArrayExpression<'_>) -> Py {
        let mut items = Vec::new();
        for element in &a.elements {
            match element {
                ArrayExpressionElement::SpreadElement(s) => {
                    let value = self.expr(&s.argument);
                    items.push(format!("*{}", value.at(ATOM)));
                }
                ArrayExpressionElement::Elision(e) => {
                    self.refuse(e.span, "array hole");
                }
                other => {
                    let e = other
                        .as_expression()
                        .expect("an array element is an expression");
                    items.push(self.expr(e).code);
                }
            }
        }
        Py {
            pure: items.is_empty(),
            ..Py::atom(format!("[{}]", items.join(", ")))
        }
    }

    fn object(&mut self, o: &ObjectExpression<'_>) -> Py {
        let mut items = Vec::new();
        for property in &o.properties {
            match property {
                ObjectPropertyKind::SpreadProperty(s) => {
                    self.refuse(s.span, "object spread");
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
                    items.push(format!("{}: {}", py_str(&key), value.code));
                }
            }
        }
        Py {
            pure: items.is_empty(),
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
                let value = self.expr(other);
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
            Op::Subtraction => {
                let left = js_num(self.expr(&b.left));
                let right = js_num(self.expr(&b.right));
                rounded(format!("{} - {}", left.at(ADD), right.at(ADD + 1)))
            }
            Op::Addition => {
                let left = self.expr(&b.left);
                let right = self.expr(&b.right);
                if left.is_num && right.is_num {
                    let (left, right) = (js_num(left), js_num(right));
                    rounded(format!("{} + {}", left.at(ADD), right.at(ADD + 1)))
                } else if left.is_str && right.is_str {
                    Py {
                        is_str: true,
                        ..Py::new(format!("{} + {}", left.at(ADD), right.at(ADD + 1)), ADD)
                    }
                } else {
                    Py::atom(format!("_js_add({}, {})", left.code, right.code))
                }
            }
            other => {
                let construct = format!("operator {}", other.as_str());
                self.refuse(b.span, construct)
            }
        }
    }

    fn strict_eq(&mut self, left: &Expression<'_>, right: &Expression<'_>, negate: bool) -> Py {
        let (l, r) = (self.expr(left), self.expr(right));
        // `x === null` / `x === undefined`: identity against the one sentinel.
        for (value, other) in [(&l, right), (&r, left)] {
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
        let exact = l.is_str || r.is_str || (l.is_num && r.is_num);
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
                Py {
                    is_num: left.is_num && right.is_num,
                    is_double: left.is_double && right.is_double,
                    is_str: left.is_str && right.is_str,
                    ..Py::atom(code)
                }
            }
        }
    }

    fn unary(&mut self, u: &UnaryExpression<'_>) -> Py {
        match u.operator {
            UnaryOperator::LogicalNot => {
                let value = truthy(self.expr(&u.argument));
                Py::boolean(format!("not {}", value.at(NOT)), NOT)
            }
            UnaryOperator::UnaryNegation => {
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

    fn args(&mut self, args: &[Argument<'_>], callback: Option<usize>) -> Option<Vec<String>> {
        let mut out = Vec::new();
        for (i, arg) in args.iter().enumerate() {
            let Some(e) = arg.as_expression() else {
                self.refuse(arg.span(), "spread argument");
                return None;
            };
            if callback == Some(i) {
                match strip(e) {
                    Expression::ArrowFunctionExpression(a) => out.push(self.callback(a).code),
                    other => {
                        self.refuse(
                            other.span(),
                            "callback that is not an inline arrow function",
                        );
                        return None;
                    }
                }
            } else {
                out.push(self.expr(e).code);
            }
        }
        Some(out)
    }

    /// An inline arrow passed as a callback: a lambda that also swallows the index and array JS
    /// passes after the element.
    fn callback(&mut self, a: &ArrowFunctionExpression<'_>) -> Py {
        if a.r#async {
            return self.refuse(a.span, "async function");
        }
        let names = self.params(&a.params);
        let body = match &a.body {
            ArrowFunctionBody::FunctionBody(b) => {
                return self.refuse(b.span, "block-bodied arrow function in a callback");
            }
            other => other
                .as_expression()
                .expect("an arrow body is a block or an expression"),
        };
        self.scopes
            .push(names.iter().map(|(src, _)| src.clone()).collect());
        let value = self.expr(body);
        self.scopes.pop();
        let mut params: Vec<String> = names.into_iter().map(|(_, py)| py).collect();
        params.push("*_".to_string());
        Py::new(
            format!("lambda {}: {}", params.join(", "), value.at(TERNARY)),
            LAMBDA,
        )
    }

    fn call(&mut self, c: &CallExpression<'_>) -> Py {
        if c.optional {
            return self.refuse(c.span, "optional call");
        }
        match strip(&c.callee) {
            Expression::Identifier(id) => {
                let callee = self.resolve(id.name.as_str(), id.span);
                let Some(args) = self.args(&c.arguments, None) else {
                    return Py::atom("None");
                };
                let is_bool = !self.scopes.iter().any(|s| s.contains(id.name.as_str()))
                    && self.bool_fns.contains(id.name.as_str());
                Py {
                    is_bool,
                    ..Py::atom(format!("{}({})", callee.code, args.join(", ")))
                }
            }
            Expression::StaticMemberExpression(m) => {
                if m.optional {
                    return self.refuse(m.span, "optional chaining");
                }
                let method = m.property.name.as_str();
                if let Expression::Identifier(object) = strip(&m.object)
                    && !self.is_local(object.name.as_str())
                {
                    return self.static_call(object.name.as_str(), method, c);
                }
                let Some(&(_, min, max, callback, returns_bool)) =
                    METHODS.iter().find(|(name, ..)| *name == method)
                else {
                    let construct = format!("builtin method .{method}");
                    return self.refuse(c.span, construct);
                };
                if c.arguments.len() < min || c.arguments.len() > max {
                    let construct = format!("argument count for .{method}");
                    return self.refuse(c.span, construct);
                }
                let receiver = self.expr(&m.object);
                let Some(args) = self.args(&c.arguments, callback) else {
                    return Py::atom("None");
                };
                let mut all = vec![receiver.code];
                all.extend(args);
                let code = format!("_js_m_{method}({})", all.join(", "));
                Py {
                    is_bool: returns_bool,
                    is_str: method == "join",
                    ..Py::atom(code)
                }
            }
            other => self.refuse(other.span(), "call of a computed callee"),
        }
    }

    fn static_call(&mut self, object: &str, method: &str, c: &CallExpression<'_>) -> Py {
        let helper = match (object, method) {
            ("Array", "isArray") => Some(("_js_is_array", true)),
            ("Number", "isInteger") => Some(("_js_number_is_integer", true)),
            ("JSON", "stringify") => Some(("_js_json_stringify", false)),
            _ => None,
        };
        let Some((helper, is_bool)) = helper else {
            let construct = format!("builtin call {object}.{method}");
            return self.refuse(c.span, construct);
        };
        if c.arguments.len() != 1 {
            let construct = format!("argument count for {object}.{method}");
            return self.refuse(c.span, construct);
        }
        let Some(args) = self.args(&c.arguments, None) else {
            return Py::atom("None");
        };
        Py {
            is_bool,
            ..Py::atom(format!("{helper}({})", args[0]))
        }
    }

    fn new_expr(&mut self, n: &NewExpression<'_>) -> Py {
        let class = match strip(&n.callee) {
            Expression::Identifier(id) if !self.is_local(id.name.as_str()) => {
                match id.name.as_str() {
                    "Map" => Some("_JsMap"),
                    "Set" => Some("_JsSet"),
                    _ => None,
                }
            }
            _ => None,
        };
        let Some(class) = class else {
            let construct = format!("new {}", self.text(n.callee.span()));
            return self.refuse(n.span, construct);
        };
        if n.arguments.len() > 1 {
            return self.refuse(n.span, "argument count for new Map/Set");
        }
        let Some(args) = self.args(&n.arguments, None) else {
            return Py::atom("None");
        };
        Py::atom(format!("{class}({})", args.join(", ")))
    }

    fn regex(&mut self, r: &RegExpLiteral<'_>) -> Py {
        if !r.regex.flags.is_empty() {
            return self.refuse(r.span, "regex flags");
        }
        let pattern = match translate_regex(r.regex.pattern.text.as_str()) {
            Ok(pattern) => pattern,
            Err(why) => return self.refuse(r.span, why),
        };
        let index = match self.regexes.iter().position(|p| *p == pattern) {
            Some(i) => i,
            None => {
                self.regexes.push(pattern);
                self.regexes.len() - 1
            }
        };
        Py {
            pure: true,
            ..Py::atom(format!("_JS_RE_{index}"))
        }
    }
}

// -------------------------------------------------------------------- helpers

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
    } else {
        Py::boolean(format!("_js_truthy({})", value.code), ATOM)
    }
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

fn returns_boolean(annotation: Option<&TSTypeAnnotation<'_>>) -> bool {
    matches!(
        annotation.map(|a| &a.type_annotation),
        Some(TSType::TSBooleanKeyword(_))
    )
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
    // Open groups: whether each is a lookahead (which takes no quantifier once closed).
    let mut groups: Vec<bool> = Vec::new();
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
                out.push('(');
                let lookahead = if chars.get(i + 1) == Some(&'?') {
                    let kind = *chars.get(i + 2).ok_or_else(syntax)?;
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
                out.push(')');
                quantifiable = !lookahead;
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
            '*' | '+' | '?' | '{' => {
                if !quantifiable {
                    return Err(format!("regex quantifier `{c}` with nothing to repeat"));
                }
                if c == '{' {
                    let close = (i..chars.len())
                        .find(|&j| chars[j] == '}')
                        .ok_or_else(syntax)?;
                    let body: String = chars[i + 1..close].iter().collect();
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
