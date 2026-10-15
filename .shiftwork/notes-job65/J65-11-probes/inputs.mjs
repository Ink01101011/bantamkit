// value strings placed after "description: " (V) or whole frontmatters (F:)
export const VALUES = [
  '|\n  hand edited\n  block', '>\n  folded\n  text', '|-\n  a\n  b', '|+\n  a\n\n', '>-\n  a\n  b',
  '|2\n   a\n  b', '>\n  a\n\n  b\n   c\n  d', '| # c\n  x', '|\n\n  x', '|\n', '|x\n  a', '|0\n  a',
  '&a x', '*a', '!foo x', '!!str 5', '!', '&', '*', '%x', '@x', '`x', '{a: 1}', '{}', '}', ']', ', x',
  '? x', '- x', '-', ': x', ':', '?', '-x', '?x', ':x', 'a | b', 'a > b', 'a & b',
  '[a, b]', "[a, 'b c', \"d\"]", '[1, 2]', '[a, b,]', '[a,b]', '[ a , b ]', '[a, [b]]', '[a: b]',
  '[a, {b: c}]', '[a,\n  b]', '[a # c]', '[a] # c', '[a]#c', '[a] x', '[a b]', '[a  b]', '[a,, b]', '[,]',
  '[]', '[ ]', '[a?b]', '[-x]', '[? x]', '[:x]', '[a:b]', '[a: ]', '[a #b]', '[a#b]', "['a''b']", '[a]  ',
  '#c', ' #c', '  x', "  'x'", "'x' #c", "'x'#c", '\tx', 'x\t', '[2026-01-02, true, null, ~]', '[a, ]', '[ , a]',
  '|\n  a\n x', '|\n  a\n  - b', '|\n\ta', '|\n  a\tb', '>\n  a\n  \tb', '|1\n  a', '|9\n  a', '|-2\n   a', '|2-\n   a',
  '|\n  x\n#c', '|\n  x\n  #c', '|\n  x\n\n\n', '|+\n  x\n\n\n', '|-\n  x\n\n\n', '>\n\n  a\n\n\n  b\n', '>+\n  a\n   b\n  c\n',
  '"a" ', "'a' ", '#', 'x #c', '>\n  a\n  b\n\n  c\n\n\n  d', '|\n  é ü\n  ไทย',
];
export const FRONTS = [
  'name: n\ndescription: d\ntype: project\nlinks: [a, b]\n',
  'name: n\ndescription: d\ntype: project\nlinks:\n- |\n  x\n- y\n',
  'name: n\ndescription: d\ntype: project\nlinks:\n- [a]\n',
  'name: n\ndescription: d\ntype: project\nlinks:\n- &a x\n',
  'name: n\ndescription:\n  hello\ntype: project\n',
  'name: n\ndescription: #c\n  hello\ntype: project\n',
  'name: n\ndescription: |\ntype: project\n',
  'name: n\ndescription: >\n  x\n\ntype: project\n',
];
