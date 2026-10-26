// Parse only: never import, evaluate, or execute the supplied script.
const fs = require('node:fs');
const acorn = require('acorn');
const input = fs.readFileSync(0, 'utf8');
if (Buffer.byteLength(input) > 2 * 1024 * 1024) throw Error('input exceeds bound');
const source = JSON.parse(input).source;
if (typeof source !== 'string' || Buffer.byteLength(source) > 1024 * 1024) throw Error('source exceeds bound');
const result = { parser: 'acorn', parser_version: acorn.version, syntax_ok: false,
  imports: [], registrations: [], dynamic_reasons: [], registration_scan_complete: false };
try {
  const ast = acorn.parse(source, { ecmaVersion: 'latest', sourceType: 'module', locations: true });
  result.syntax_ok = true;
  const aliases = new Set();
  for (const statement of ast.body) {
    if (statement.type === 'ImportDeclaration') {
      result.imports.push(statement.source.value);
      if (statement.source.value === 'cs_script/point_script') {
        for (const spec of statement.specifiers) {
          if (spec.type === 'ImportSpecifier' && spec.imported.name === 'Instance') aliases.add(spec.local.name);
        }
      }
    }
  }
  const names = pattern => {
    if (!pattern) return [];
    if (pattern.type === 'Identifier') return [pattern.name];
    if (pattern.type === 'RestElement') return names(pattern.argument);
    if (pattern.type === 'AssignmentPattern') return names(pattern.left);
    if (pattern.type === 'ArrayPattern') return pattern.elements.flatMap(names);
    if (pattern.type === 'ObjectPattern') return pattern.properties.flatMap(p => names(p.value || p.argument));
    return [];
  };
  const stack = [[ast, false, null]];
  let count = 0;
  while (stack.length) {
    const [node, conditional, parent] = stack.pop();
    if (++count > 200000) throw Error('AST node budget exceeded');
    let bindings = [];
    if (node.type === 'VariableDeclarator') bindings = names(node.id);
    if (/Function/.test(node.type)) bindings = [...names(node.id), ...node.params.flatMap(names)];
    if (node.type === 'CatchClause') bindings = names(node.param);
    if (bindings.some(n => aliases.has(n))) result.dynamic_reasons.push('shadowed_instance_binding');
    if ((node.type === 'VariableDeclarator' && aliases.has(node.init?.name)) ||
        (node.type === 'AssignmentExpression' && aliases.has(node.right?.name)) ||
        (node.type === 'CallExpression' && node.arguments.some(a => a.type === 'Identifier' && aliases.has(a.name)))) {
      result.dynamic_reasons.push('instance_binding_escapes_static_analysis');
    }
    if (node.type === 'ImportExpression' || (['CallExpression','NewExpression'].includes(node.type) && ['eval','Function'].includes(node.callee.name))) {
      result.dynamic_reasons.push('dynamic_code_or_import');
    }
    if (node.type === 'MemberExpression') {
      const property = node.computed ? node.property.value : node.property.name;
      if (property === 'OnScriptInput' && !(parent?.type === 'CallExpression' && parent.callee === node)) result.dynamic_reasons.push('indirect_registration_reference');
      if (node.object.type === 'Identifier' && aliases.has(node.object.name) && node.computed && typeof node.property.value !== 'string') result.dynamic_reasons.push('dynamic_instance_member');
    }
    if (node.type === 'ExportNamedDeclaration' || node.type === 'ExportAllDeclaration') {
      if (node.source) result.imports.push(node.source.value);
    }
    if (node.type === 'CallExpression' && node.callee.type === 'MemberExpression') {
      const member = node.callee;
      const property = member.computed ? member.property.value : member.property.name;
      if (property === 'OnScriptInput') {
        const receiverKnown = member.object.type === 'Identifier' && aliases.has(member.object.name);
        const literal = node.arguments[0]?.type === 'Literal' && typeof node.arguments[0].value === 'string';
        const callback = node.arguments[1];
        const callbackKnown = callback && ['FunctionExpression','ArrowFunctionExpression'].includes(callback.type);
        if (!receiverKnown || !literal || conditional || !callbackKnown) result.dynamic_reasons.push('dynamic_or_conditional_registration');
        if (receiverKnown && literal) result.registrations.push({ name: node.arguments[0].value,
          line: node.loc.start.line, conditional, argument_count: node.arguments.length,
          callback_kind: callback?.type || 'missing', callback_arity: callbackKnown ? callback.params.length : null });
      }
    }
    const nested = conditional || /Function/.test(node.type) || ['IfStatement','ConditionalExpression','LogicalExpression','ChainExpression',
      'ForStatement','ForOfStatement','ForInStatement','WhileStatement','DoWhileStatement','TryStatement','SwitchStatement'].includes(node.type);
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        for (const child of value) if (child && typeof child.type === 'string') stack.push([child, nested, node]);
      } else if (value && typeof value.type === 'string') stack.push([value, nested, node]);
    }
  }
  result.dynamic_reasons = [...new Set(result.dynamic_reasons)];
  if (result.registrations.length > 4096 || result.imports.length > 1024) throw Error('analysis output budget exceeded');
  result.registration_scan_complete = result.dynamic_reasons.length === 0;
} catch (error) {
  result.error = String(error.message);
  if (error.loc) result.error_location = error.loc;
}
process.stdout.write(JSON.stringify(result));
