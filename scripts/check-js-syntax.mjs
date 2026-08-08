#!/usr/bin/env node
// Validates standalone JavaScript and inline <script> blocks without a browser.
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { spawnSync } from 'node:child_process';

function syntaxCheck(path, source) {
  const dir = mkdtempSync(join(tmpdir(), 'shipyard-js-check-'));
  const candidate = join(dir, `${basename(path)}.js`);
  try {
    writeFileSync(candidate, source);
    const result = spawnSync(process.execPath, ['--check', candidate], { encoding: 'utf8' });
    if (result.status !== 0) {
      process.stderr.write(`${path}: JavaScript syntax error\n${result.stderr}`);
      return false;
    }
    return true;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function checkFile(path) {
  const source = readFileSync(path, 'utf8');
  if (!path.endsWith('.html')) return syntaxCheck(path, source);
  let valid = true;
  const scripts = source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi);
  let index = 0;
  for (const match of scripts) {
    if (/\bsrc\s*=/i.test(match[1])) continue;
    index += 1;
    valid = syntaxCheck(`${path}:inline-script-${index}`, match[2]) && valid;
  }
  return valid;
}

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error('usage: check-js-syntax.mjs <.js-or-.html>...');
  process.exit(2);
}
process.exit(files.every(checkFile) ? 0 : 1);
