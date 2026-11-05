// Transpile actual UI modules for offline Node rendering tests without emitting files.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
function loadSource(relative, mocks = {}) {
  let filename = path.resolve(__dirname, '../src', relative);
  if (!path.extname(filename)) filename += fs.existsSync(filename + '.ts') ? '.ts' : '.tsx';
  const mod = new Module(filename, module);
  mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const native = mod.require.bind(mod);
  mod.require = name => name in mocks ? mocks[name] : name.startsWith('@/') ? loadSource(name.slice(2), mocks)
    : name.startsWith('./') ? loadSource(path.resolve(path.dirname(filename), name), mocks) : native(name);
  mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return mod.exports;
}
module.exports = { loadSource };
