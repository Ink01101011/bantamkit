//! Python spelling: string literals, number literals and identifier names.

/// Python keywords: an identifier that spells one gets a trailing `_`.
const KEYWORDS: &[&str] = &[
    "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import",
    "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
    "with", "yield",
];

/// Builtins the runtime support module calls. A MODULE-LEVEL name that spells one would shadow it
/// for the inlined helpers, so it gets a trailing `_` too. J89-2: so does a LOCAL (a parameter
/// above all): since J87 a function body itself spells `type(x) is str`, `len(xs)` and
/// `isinstance(...)` in its guarded entry and fast paths, so `weightOf(type: string, ...)` made
/// the guard call the string (`'str' object is not callable`).
const RUNTIME_BUILTINS: &[&str] = &[
    "BaseException",
    "Exception",
    "abs",
    "all",
    "any",
    "bool",
    "callable",
    "chr",
    "dict",
    "divmod",
    "enumerate",
    "float",
    "frozenset",
    "getattr",
    "hash",
    "id",
    "int",
    "isinstance",
    "iter",
    "len",
    "list",
    "max",
    "min",
    "object",
    "ord",
    "range",
    "repr",
    "reversed",
    "set",
    "setattr",
    "sorted",
    "str",
    "super",
    "type",
    "TypeError",
    "ValueError",
];

/// `camelCase` / `PascalCase` to `snake_case`. An all-caps name (`MAX_WIDTH`) is kept as written;
/// an acronym run stays one word (`parseJSONValue` -> `parse_json_value`).
pub fn snake_case(name: &str) -> String {
    let chars: Vec<char> = name.chars().collect();
    if chars
        .iter()
        .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || *c == '_')
        && chars.iter().any(|c| c.is_ascii_uppercase())
    {
        return name.to_string();
    }
    let mut out = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if c.is_ascii_uppercase() {
            let prev = if i > 0 { Some(chars[i - 1]) } else { None };
            let next = chars.get(i + 1).copied();
            let boundary = match prev {
                Some(p) if p.is_ascii_lowercase() || p.is_ascii_digit() => true,
                Some(p) if p.is_ascii_uppercase() => next.is_some_and(|n| n.is_ascii_lowercase()),
                _ => false,
            };
            if boundary && !out.ends_with('_') {
                out.push('_');
            }
            out.push(c.to_ascii_lowercase());
        } else {
            out.push(c);
        }
    }
    out
}

/// `name` is a Python keyword (so it cannot be an attribute spelled `obj.name`).
pub fn is_py_keyword(name: &str) -> bool {
    KEYWORDS.contains(&name)
}

/// The Python name for a source binding. `module_level` adds the builtin guard; `private` adds the
/// leading underscore a non-exported module-level name carries.
pub fn py_name(name: &str, module_level: bool, private: bool) -> String {
    let mut out = snake_case(name);
    if private && !out.starts_with('_') {
        out.insert(0, '_');
    }
    let _ = module_level;
    if KEYWORDS.contains(&out.as_str()) || RUNTIME_BUILTINS.contains(&out.as_str()) {
        out.push('_');
    }
    out
}

/// A double-quoted Python string literal from UTF-16 code units, so a lone surrogate survives as
/// `\udxxx`. Non-ASCII printable characters are written as themselves (the file is UTF-8).
pub fn py_str_utf16(units: impl IntoIterator<Item = u16>) -> String {
    let mut out = String::from("\"");
    for decoded in char::decode_utf16(units) {
        match decoded {
            Ok(c) => push_char(&mut out, c),
            Err(err) => out.push_str(&format!("\\u{:04x}", err.unpaired_surrogate())),
        }
    }
    out.push('"');
    out
}

/// A double-quoted Python string literal from a Rust string.
pub fn py_str(text: &str) -> String {
    py_str_utf16(text.encode_utf16())
}

fn push_char(out: &mut String, c: char) {
    match c {
        '\\' => out.push_str("\\\\"),
        '"' => out.push_str("\\\""),
        '\n' => out.push_str("\\n"),
        '\r' => out.push_str("\\r"),
        '\t' => out.push_str("\\t"),
        c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\x{:02x}", c as u32)),
        c if matches!(c as u32, 0x80..=0x9f | 0x2028 | 0x2029 | 0xfeff) => {
            out.push_str(&format!("\\u{:04x}", c as u32))
        }
        c => out.push(c),
    }
}

/// A JS number literal as a Python literal: an integral value below 2^53 is an `int`, anything
/// else a float spelled by Rust's shortest round-trip formatting. `None` for a non-finite value.
pub fn py_number(value: f64) -> Option<String> {
    if !value.is_finite() {
        return None;
    }
    if value.fract() == 0.0 && value.abs() < 9_007_199_254_740_992.0 {
        if value == 0.0 && value.is_sign_negative() {
            return Some("-0.0".to_string());
        }
        return Some(format!("{}", value as i64));
    }
    let text = format!("{value:?}");
    Some(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snake() {
        assert_eq!(snake_case("touchesRefusal"), "touches_refusal");
        assert_eq!(snake_case("plan"), "plan");
        assert_eq!(snake_case("parseJSONValue"), "parse_json_value");
        assert_eq!(snake_case("MAX_WIDTH"), "MAX_WIDTH");
        assert_eq!(snake_case("depends_on"), "depends_on");
        assert_eq!(snake_case("PlanNode"), "plan_node");
        assert_eq!(snake_case("v2Name"), "v2_name");
    }

    #[test]
    fn names() {
        assert_eq!(py_name("refuse", true, true), "_refuse");
        assert_eq!(py_name("isInteger", true, true), "_is_integer");
        assert_eq!(py_name("lambda", false, false), "lambda_");
        assert_eq!(py_name("len", true, false), "len_");
        // J89-2: a local is guarded too (a generated body calls `type(...)` itself).
        assert_eq!(py_name("id", false, false), "id_");
        assert_eq!(py_name("type", false, false), "type_");
        assert_eq!(py_name("node", false, false), "node");
    }

    #[test]
    fn strings() {
        assert_eq!(py_str("a\"b\\c\n"), "\"a\\\"b\\\\c\\n\"");
        assert_eq!(py_str("é"), "\"é\"");
        assert_eq!(py_str_utf16([0xd800u16]), "\"\\ud800\"");
    }

    #[test]
    fn numbers() {
        assert_eq!(py_number(3.0).unwrap(), "3");
        assert_eq!(py_number(0.5).unwrap(), "0.5");
        assert_eq!(py_number(1e-7).unwrap(), "1e-7");
        assert!(py_number(f64::INFINITY).is_none());
    }
}
