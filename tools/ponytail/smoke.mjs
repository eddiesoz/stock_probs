// Exercise the vendored plugin in a disposable config home without reading credentials.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const checkout = path.dirname(fileURLToPath(import.meta.url));
const temporaryConfig = fs.mkdtempSync(path.join(os.tmpdir(), 'stock-probs-ponytail-'));
process.env.XDG_CONFIG_HOME = temporaryConfig;
process.env.PONYTAIL_DEFAULT_MODE = 'full';

const reads = [];
const writes = [];
const originalRead = fs.readFileSync;
const originalReaddir = fs.readdirSync;
const originalWrite = fs.writeFileSync;
fs.readFileSync = function monitoredRead(file, ...args) {
  reads.push(path.resolve(String(file)));
  return originalRead.call(this, file, ...args);
};
fs.readdirSync = function monitoredReaddir(directory, ...args) {
  reads.push(path.resolve(String(directory)));
  return originalReaddir.call(this, directory, ...args);
};
fs.writeFileSync = function monitoredWrite(file, ...args) {
  writes.push(path.resolve(String(file)));
  return originalWrite.call(this, file, ...args);
};

try {
  const module = await import(pathToFileURL(path.join(checkout, '.opencode/plugins/ponytail.mjs')).href);
  assert.deepEqual(Object.keys(module), ['default']);
  assert.equal(typeof module.default, 'function');

  const hooks = await module.default({ client: { app: { log() {} } } });
  assert.deepEqual(Object.keys(hooks).sort(), [
    'command.execute.before',
    'config',
    'experimental.chat.system.transform',
  ]);
  assert.equal('tool' in hooks, false);
  assert.equal('auth' in hooks, false);

  const config = { skills: { paths: ['.opencode/skills'] } };
  await hooks.config(config);
  assert.deepEqual(Object.keys(config.command).sort(), [
    'ponytail',
    'ponytail-audit',
    'ponytail-debt',
    'ponytail-gain',
    'ponytail-help',
    'ponytail-review',
  ]);
  assert.deepEqual(config.skills.paths, ['.opencode/skills', path.join(checkout, 'skills')]);

  const output = { system: [] };
  await hooks['experimental.chat.system.transform']({}, output);
  assert.equal(output.system.length, 1);
  assert.match(output.system[0], /PONYTAIL MODE ACTIVE — level: full/);

  const brokerPrompt = 'This agent is reserved for system use. Do not invoke directly.';
  const brokerOutput = { system: [brokerPrompt, 'request instructions'] };
  await hooks['experimental.chat.system.transform']({}, brokerOutput);
  assert.deepEqual(brokerOutput.system, [brokerPrompt, 'request instructions']);
  await hooks['command.execute.before']({ command: 'ponytail-review', arguments: '' });

  assert.deepEqual(writes, []);
  assert.ok(reads.length > 0);
  assert.ok(reads.every((file) => file.startsWith(checkout + path.sep) || file.startsWith(temporaryConfig + path.sep)));
  assert.ok(reads.every((file) => !/(credential|secret|token|password|auth)/i.test(file)));
} finally {
  fs.readFileSync = originalRead;
  fs.readdirSync = originalReaddir;
  fs.writeFileSync = originalWrite;
  fs.rmSync(temporaryConfig, { recursive: true, force: true });
}

console.log('ponytail plugin smoke: pass');
