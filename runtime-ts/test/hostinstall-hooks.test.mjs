/**
 * `--install-hooks` / `--remove-hooks`: the seven entries, and the consent that gates them.
 *
 * THE FILE UNDER TEST IS THE USER'S OWN `~/.claude/settings.json`, so every case here points
 * `HOME`/`USERPROFILE` at a scratch directory BEFORE the module resolves a path, and asserts
 * the redirection rather than believing it. A test that reached the real file would register
 * seven hooks on the machine it was measuring — which is the exact thing RULING Q3.3 exists
 * to stop a PROGRAM doing without being asked.
 *
 * NO CASE HERE NEEDS A TERMINAL. The three-state consent gate takes `ask` as a seam: a
 * function for "there is a terminal, here is the answer", and `null` for "there is none".
 * `cli.ts` supplies the real one off `process.stdin.isTTY`; nothing in this file does, which
 * is what makes the refusing states testable at all.
 *
 * THE TWO REFUSING STATES ARE ASSERTED ON THE BYTES, NOT ON THE EXIT. "It threw" is satisfied
 * by a program that wrote the file and then threw. Every refusal case below reads the settings
 * file before and after and compares Buffers, and asserts that no `.backup-` sibling appeared.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const OWN_CLI = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');

/** The install shape seam, so no case can reach npm or the network. */
const CHECKOUT = { shape: () => 'checkout' };

/** Run `body` with HOME pointed at a fresh scratch directory, then put the world back. */
async function withHome(body) {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-'));
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = root;
  process.env.USERPROFILE = root;
  try {
    assert.equal(homedir(), root, 'homedir() did not follow HOME; this test would edit a real settings file');
    const hostinstall = await import('../dist/hostinstall.js');
    assert.ok(
      hostinstall.claudeSettingsPath().startsWith(root),
      `claudeSettingsPath() escaped the scratch HOME: ${hostinstall.claudeSettingsPath()}`,
    );
    await body(hostinstall, root);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(root, { recursive: true, force: true });
  }
}

const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));
const backupsIn = (path) => (existsSync(dirname(path)) ? readdirSync(dirname(path)).filter((n) => n.includes('.backup-')) : []);

/** A settings file that is not ours, written byte-exactly so a comparison means something. */
function seed(path, text) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, 'utf8');
  return readFileSync(path);
}

/** A hook entry nobody named bantamkit wrote. It must survive everything in this file. */
const FOREIGN = {
  matcher: 'Bash',
  hooks: [{ type: 'command', command: '/opt/acme/audit.sh', timeout: 5 }],
};

/** A `tell` that records every line the gate printed. */
function recorder() {
  const said = [];
  return { said, tell: (text) => said.push(text) };
}

// ------------------------------------------------------------------ the fixed data

test('the seven events and their matchers are the fixed data, in the ruled order', async () => {
  const { HOOK_EVENTS } = await import('../dist/hostinstall.js');
  assert.deepEqual(
    HOOK_EVENTS.map(([event]) => event),
    ['SessionStart', 'PreToolUse', 'PostToolUse', 'UserPromptSubmit', 'PreCompact', 'PostCompact', 'Stop'],
  );
  assert.deepEqual(new Map(HOOK_EVENTS).get('SessionStart'), 'startup|resume|clear|compact');
  assert.deepEqual(new Map(HOOK_EVENTS).get('PreToolUse'), 'Read');
  // MATCHER-LESS ON PURPOSE. The PostToolUse arm logs a usage event for EVERY tool call and
  // runs the memory_save half only when the tool was that one; a second, narrower entry
  // beside it would fire the save half twice.
  assert.equal(new Map(HOOK_EVENTS).get('PostToolUse'), null);
  assert.equal(HOOK_EVENTS.length, 7);
});

test('the settings path is ~/.claude/settings.json and nothing else', async () => {
  await withHome(async (h, root) => {
    assert.equal(h.claudeSettingsPath(), join(root, '.claude', 'settings.json'));
  });
});

// ------------------------------------------------------------------ the happy path

test('a first install writes seven entries, after asking, and reports what it did', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    let asked = 0;
    const { said, tell } = recorder();
    const report = h.installHooks({ ...CHECKOUT, tell, ask: () => (asked += 1, true) });
    assert.equal(asked, 1, 'it must ask exactly once');
    const hooks = readJson(path).hooks;
    assert.deepEqual(Object.keys(hooks), [
      'SessionStart',
      'PreToolUse',
      'PostToolUse',
      'UserPromptSubmit',
      'PreCompact',
      'PostCompact',
      'Stop',
    ]);
    for (const [event, entries] of Object.entries(hooks)) {
      assert.equal(entries.length, 1, event);
      assert.equal(entries[0].hooks[0].type, 'command');
      assert.equal(entries[0].hooks[0].timeout, 10);
      assert.ok(entries[0].hooks[0].command.endsWith(' --hook'), entries[0].hooks[0].command);
    }
    assert.ok(report.startsWith('installed bantamkit hooks into '), report);
    // The plan went out BEFORE the question, so it is in `said` whether or not it was read.
    assert.ok(said.join('').includes('bantamkit would add 7 hook entries to '), said.join(''));
  });
});

test('the plan is the ruled five lines, in the ruled order', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    seed(path, '{}\n');
    const { said, tell } = recorder();
    h.installHooks({ ...CHECKOUT, tell, ask: () => true });
    const plan = said.join('').split('\n');
    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const stamp = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
    assert.equal(plan[0], `bantamkit would add 7 hook entries to ${path}`);
    assert.equal(
      plan[1],
      '  events : SessionStart PreToolUse PostToolUse UserPromptSubmit PreCompact PostCompact Stop',
    );
    assert.ok(plan[2].startsWith('  command: '), plan[2]);
    assert.ok(plan[2].endsWith(' --hook'), plan[2]);
    assert.equal(plan[3], `  backup : ${path}.backup-${stamp}`);
    assert.equal(plan[4], 'Existing hooks are left byte-for-byte; only entries naming bantamkit are replaced.');
  });
});

test('there is no backup line in the plan when there is no file to back up', async () => {
  await withHome(async (h) => {
    const { said, tell } = recorder();
    h.installHooks({ ...CHECKOUT, tell, ask: () => true });
    assert.ok(!said.join('').includes('backup :'), said.join(''));
  });
});

test('a second identical install changes nothing, says so, and never asks', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const before = readFileSync(path);
    const report = h.installHooks({
      ...CHECKOUT,
      tell: () => assert.fail('a no-op install printed a plan'),
      ask: () => assert.fail('a no-op install asked for consent'),
    });
    assert.equal(report, `bantamkit hooks are already installed in ${path} and match`);
    assert.deepEqual(readFileSync(path), before);
    assert.deepEqual(backupsIn(path), []);
  });
});

test('--yes writes with no terminal at all and never asks', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const { said, tell } = recorder();
    const report = h.installHooks({ ...CHECKOUT, tell, yes: true, ask: null });
    assert.ok(report.startsWith('installed bantamkit hooks into '), report);
    assert.equal(Object.keys(readJson(path).hooks).length, 7);
    // The plan is still printed: it is what the person is consenting to in advance.
    assert.ok(said.join('').includes('bantamkit would add 7 hook entries to '), said.join(''));
  });
});

// ------------------------------------------------------- the two states that write NOTHING

test('no terminal and no --yes refuses with the ruled sentence and leaves the file byte-unchanged', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const before = seed(path, `${JSON.stringify({ hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
    const { said, tell } = recorder();
    assert.throws(
      () => h.installHooks({ ...CHECKOUT, tell, ask: null }),
      (e) => {
        assert.equal(e.constructor.name, 'HookConsentUnavailable');
        assert.equal(
          e.message,
          '--install-hooks writes your ~/.claude/settings.json and needs a terminal to ask.\n' +
            'There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n' +
            '--yes to say yes in advance.',
        );
        return true;
      },
    );
    assert.deepEqual(readFileSync(path), before, 'the refusal wrote to the settings file');
    assert.deepEqual(backupsIn(path), [], 'the refusal took a backup, so it was about to write');
    assert.equal(said.join(''), '', 'the refusal printed a plan for a write it was never going to do');
  });
});

for (const answer of ['no', '', 'yes', 'YES', 'n', 'N', ' ']) {
  test(`answering ${JSON.stringify(answer)} writes nothing and says so`, async () => {
    await withHome(async (h) => {
      const path = h.claudeSettingsPath();
      const before = seed(path, `${JSON.stringify({ hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
      assert.throws(
        () => h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => answer.trim() === 'y' || answer.trim() === 'Y' }),
        (e) => {
          assert.equal(e.constructor.name, 'HookDeclined');
          assert.equal(e.message, 'no hooks were written');
          return true;
        },
      );
      assert.deepEqual(readFileSync(path), before, 'a declined install wrote to the settings file');
      assert.deepEqual(backupsIn(path), [], 'a declined install took a backup');
    });
  });
}

for (const answer of ['y', 'Y']) {
  test(`answering ${JSON.stringify(answer)} is the only thing that writes`, async () => {
    await withHome(async (h) => {
      const path = h.claudeSettingsPath();
      h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => answer === 'y' || answer === 'Y' });
      assert.equal(Object.keys(readJson(path).hooks).length, 7);
    });
  });
}

// -------------------------------------------------------------- somebody else's hooks

test('a foreign hook entry survives an install, byte for byte', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    seed(path, `${JSON.stringify({ model: 'opus', hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const after = readJson(path);
    assert.equal(after.model, 'opus', 'an unrelated settings key was dropped');
    assert.deepEqual(after.hooks.PreToolUse[0], FOREIGN, 'the foreign entry was rewritten');
    assert.equal(after.hooks.PreToolUse.length, 2, 'ours was not appended beside it');
    assert.equal(after.hooks.PreToolUse[1].matcher, 'Read');
  });
});

test('an existing bantamkit entry is replaced, never duplicated', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    seed(
      path,
      `${JSON.stringify(
        {
          hooks: {
            Stop: [{ hooks: [{ type: 'command', command: '/old/path/to/bantamkit-mcp --hook', timeout: 10 }] }]
          },
        },
        null,
        2,
      )}\n`,
    );
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const stop = readJson(path).hooks.Stop;
    assert.equal(stop.length, 1, 'the stale bantamkit entry was kept beside the new one');
    assert.ok(!JSON.stringify(stop).includes('/old/path/to/'), JSON.stringify(stop));
  });
});

test('the backup holds the bytes that were there before the write', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const before = seed(path, `${JSON.stringify({ hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const copies = backupsIn(path);
    assert.equal(copies.length, 1, JSON.stringify(copies));
    assert.deepEqual(readFileSync(join(dirname(path), copies[0])), before);
  });
});

test('a settings file that does not parse is never overwritten', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const before = seed(path, '{ "hooks": ');
    assert.throws(
      () => h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true }),
      (e) => {
        assert.equal(e.constructor.name, 'InstallError');
        assert.ok(e.message.startsWith(`${path} is not valid JSON, so this refuses to touch it: `), e.message);
        return true;
      },
    );
    assert.deepEqual(readFileSync(path), before);
    assert.deepEqual(backupsIn(path), []);
  });
});

test('a hooks key that is not an object is refused by name', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const before = seed(path, `${JSON.stringify({ hooks: ['nope'] }, null, 2)}\n`);
    assert.throws(
      () => h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true }),
      (e) => {
        assert.equal(e.message, `${path} has a 'hooks' that is not an object; refusing to touch it`);
        return true;
      },
    );
    assert.deepEqual(readFileSync(path), before);
  });
});

test('one event whose value is not a list is refused by name', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const before = seed(path, `${JSON.stringify({ hooks: { Stop: { nope: 1 } } }, null, 2)}\n`);
    assert.throws(
      () => h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true }),
      (e) => {
        assert.equal(e.message, `${path} has a 'hooks.Stop' that is not a list; refusing to touch it`);
        return true;
      },
    );
    assert.deepEqual(readFileSync(path), before);
  });
});

// ------------------------------------------------------------------------- --remove-hooks

test('--remove-hooks takes out only what bantamkit wrote', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    seed(path, `${JSON.stringify({ model: 'opus', hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const report = h.removeHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const after = readJson(path);
    assert.equal(after.model, 'opus');
    assert.deepEqual(after.hooks, { PreToolUse: [FOREIGN] }, 'the foreign entry did not survive intact');
    assert.ok(report.startsWith(`removed bantamkit hooks from ${path}`), report);
  });
});

/*
 * THE CONSENT GATE ON REMOVAL — the user's ruling of 2026-09-20, which OVERTURNS RULING Q3.7.
 *
 * Q3.7 said removal needed no prompt, because taking back out what bantamkit put in is not a
 * write to somebody else's configuration. That was written by the spec subagent, not by the
 * user, and the day it shipped an unsandboxed probe let the abbreviation `--remove` resolve to
 * `--remove-hooks` and it rewrote the operator's REAL `~/.claude/settings.json`: 256 lines went
 * to 188, twelve hook-event keys to ten, and `PreCompact`/`PostCompact` were gone. It needed no
 * terminal and no `--yes` to do it.
 *
 * So removal now takes the SAME three-state gate as install, and the cases below are install's
 * cases with the verb changed, deliberately: two flags that touch the same file must not grow
 * two different consent stories.
 */

test('--remove-hooks asks before it removes, and honours a yes', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    let asked = 0;
    const { said, tell } = recorder();
    const report = h.removeHooks({ ...CHECKOUT, tell, ask: () => (asked += 1, true) });
    assert.equal(asked, 1, 'it must ask exactly once');
    assert.deepEqual(readJson(path).hooks, {});
    assert.ok(report.startsWith(`removed bantamkit hooks from ${path}`), report);
    assert.ok(said.join('').includes('bantamkit would remove 7 hook entries from '), said.join(''));
  });
});

test('the removal plan is the four ruled lines, in order', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const { said, tell } = recorder();
    h.removeHooks({ ...CHECKOUT, tell, ask: () => true });
    const printed = said.join('');
    const lines = printed.split('\n');
    assert.equal(lines[0], `bantamkit would remove 7 hook entries from ${path}`);
    assert.equal(
      lines[1],
      '  events : SessionStart PreToolUse PostToolUse UserPromptSubmit PreCompact PostCompact Stop',
    );
    assert.match(lines[2], /^ {2}backup : .*\.backup-\d{4}-\d{2}-\d{2}$/);
    assert.equal(
      lines[3],
      'Existing hooks are left byte-for-byte; only entries naming bantamkit are removed.',
    );
    assert.equal(lines[4], '', 'the plan must end with exactly one newline');
    assert.equal(lines.length, 5, printed);
  });
});

test('--remove-hooks with no terminal and no --yes refuses and leaves the file byte-unchanged', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const before = readFileSync(path);
    const { said, tell } = recorder();
    assert.throws(
      () => h.removeHooks({ ...CHECKOUT, tell, ask: null }),
      (e) => {
        assert.equal(e.constructor.name, 'HookConsentUnavailable');
        assert.equal(
          e.message,
          '--remove-hooks rewrites your ~/.claude/settings.json and needs a terminal to ask.\n' +
            'There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n' +
            '--yes to say yes in advance.',
        );
        return true;
      },
    );
    assert.deepEqual(readFileSync(path), before, 'the refusal wrote to the settings file');
    assert.deepEqual(backupsIn(path), [], 'the refusal took a backup, so it was about to write');
    assert.equal(said.join(''), '', 'the refusal printed a plan for a write it was never going to do');
  });
});

for (const answer of ['no', '', 'yes', 'YES', 'n', 'N', ' ']) {
  test(`--remove-hooks answered ${JSON.stringify(answer)} removes nothing and says so`, async () => {
    await withHome(async (h) => {
      const path = h.claudeSettingsPath();
      h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
      const before = readFileSync(path);
      assert.throws(
        () => h.removeHooks({ ...CHECKOUT, tell: () => {}, ask: () => answer.trim() === 'y' || answer.trim() === 'Y' }),
        (e) => {
          assert.equal(e.constructor.name, 'HookDeclined');
          assert.equal(e.message, 'no hooks were removed');
          return true;
        },
      );
      assert.deepEqual(readFileSync(path), before, 'a declined removal wrote to the settings file');
      assert.deepEqual(backupsIn(path), [], 'a declined removal took a backup');
    });
  });
}

test('--remove-hooks --yes removes with no terminal at all and never asks', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const { said, tell } = recorder();
    const report = h.removeHooks({ ...CHECKOUT, tell, yes: true, ask: null });
    assert.ok(report.startsWith(`removed bantamkit hooks from ${path}`), report);
    assert.deepEqual(readJson(path).hooks, {});
    // The plan is still printed: it is what the person consented to in advance.
    assert.ok(said.join('').includes('bantamkit would remove 7 hook entries from '), said.join(''));
  });
});

test('the removal plan names only the events that actually lose an entry', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    seed(
      path,
      `${JSON.stringify(
        {
          hooks: {
            PreToolUse: [FOREIGN],
            Stop: [{ hooks: [{ type: 'command', command: '/opt/bantamkit/x --hook', timeout: 10 }] }],
          },
        },
        null,
        2,
      )}\n`,
    );
    const { said, tell } = recorder();
    h.removeHooks({ ...CHECKOUT, tell, yes: true, ask: null });
    const lines = said.join('').split('\n');
    assert.equal(lines[0], `bantamkit would remove 1 hook entries from ${path}`);
    assert.equal(lines[1], '  events : Stop');
  });
});

test('--remove-hooks on a file with no bantamkit hooks changes nothing and says so', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    const before = seed(path, `${JSON.stringify({ hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
    // THE NO-OP RETURNS BEFORE THE GATE, exactly as a second `--install-hooks` does. There is
    // no write to consent to, so this must stay exit 0 with no terminal — which is what keeps
    // `--remove-hooks` safe to put in a teardown script.
    const report = h.removeHooks({
      ...CHECKOUT,
      ask: () => assert.fail('a removal with nothing to remove asked for consent'),
      tell: () => assert.fail('a removal with nothing to remove printed a plan'),
    });
    assert.equal(report, `no bantamkit hooks are installed in ${path}`);
    assert.deepEqual(readFileSync(path), before, 'a no-op removal rewrote the settings file');
    assert.deepEqual(backupsIn(path), [], 'a no-op removal took a backup');
  });
});

test('--remove-hooks with no settings file at all writes nothing', async () => {
  await withHome(async (h, root) => {
    const path = h.claudeSettingsPath();
    const report = h.removeHooks({
      ...CHECKOUT,
      ask: () => assert.fail('a removal with no file at all asked for consent'),
      tell: () => {},
    });
    assert.equal(report, `no bantamkit hooks are installed in ${path}`);
    assert.equal(existsSync(path), false, '--remove-hooks created the file it had nothing to remove from');
    assert.equal(existsSync(join(root, '.claude')), false, '--remove-hooks created ~/.claude');
  });
});

test('--remove-hooks still takes the dated backup', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const before = readFileSync(path);
    h.removeHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    const copies = backupsIn(path);
    assert.equal(copies.length, 1, JSON.stringify(copies));
    assert.deepEqual(readFileSync(join(dirname(path), copies[0])), before);
  });
});

test('an event left with no entries loses its key rather than holding an empty list', async () => {
  await withHome(async (h) => {
    const path = h.claudeSettingsPath();
    h.installHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    h.removeHooks({ ...CHECKOUT, tell: () => {}, ask: () => true });
    assert.deepEqual(readJson(path).hooks, {});
  });
});

// ------------------------------------------------------- the real CLI, in a scratch HOME

/** The real process, with HOME redirected in its ENVIRONMENT — no import-time trust at all. */
function runCli(argv, root, input = '') {
  return spawnSync(process.execPath, [OWN_CLI, ...argv], {
    input,
    encoding: 'utf8',
    env: { ...process.env, HOME: root, USERPROFILE: root },
  });
}

test('the real CLI with no terminal and no --yes exits 2 and writes nothing', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    const path = join(root, '.claude', 'settings.json');
    const before = seed(path, `${JSON.stringify({ hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
    const r = runCli(['--install-hooks'], root);
    assert.equal(r.status, 2, `${r.stdout}${r.stderr}`);
    assert.equal(
      r.stderr,
      '--install-hooks writes your ~/.claude/settings.json and needs a terminal to ask.\n' +
        'There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n' +
        '--yes to say yes in advance.\n',
    );
    assert.equal(r.stdout, '');
    assert.deepEqual(readFileSync(path), before, 'the CLI wrote to the settings file it refused to touch');
    assert.deepEqual(backupsIn(path), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the real CLI with --yes writes the seven entries and exits 0', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    const r = runCli(['--install-hooks', '--yes'], root);
    assert.equal(r.status, 0, `${r.stdout}${r.stderr}`);
    const path = join(root, '.claude', 'settings.json');
    const hooks = readJson(path).hooks;
    assert.equal(Object.keys(hooks).length, 7);
    // The command recorded is THIS tree's, absolute, and it carries `--hook`.
    const command = hooks.Stop[0].hooks[0].command;
    assert.ok(command.includes(OWN_CLI), command);
    assert.ok(command.endsWith(' --hook'), command);
    assert.ok(r.stdout.startsWith(`installed bantamkit hooks into ${path}`), r.stdout);
    assert.ok(r.stderr.includes('bantamkit would add 7 hook entries to '), r.stderr);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

/*
 * THE REAL CLI, AND THE REGRESSION THAT MADE THIS UNIT EXIST.
 *
 * Until the user's ruling of 2026-09-20 the three cases below read the other way: the first
 * one exited 0 and rewrote the file with no terminal and no `--yes`, which is exactly what
 * happened to the operator's own `~/.claude/settings.json`.
 */

test('the real CLI --remove-hooks with no terminal and no --yes exits 2 and writes nothing', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    assert.equal(runCli(['--install-hooks', '--yes'], root).status, 0);
    const path = join(root, '.claude', 'settings.json');
    const before = readFileSync(path);
    // The backup the INSTALL took is already sitting there; count it, so the assertion below
    // is about what the removal added and not about what the whole directory holds.
    const backupsBefore = backupsIn(path).length;
    const r = runCli(['--remove-hooks'], root);
    assert.equal(r.status, 2, `${r.stdout}${r.stderr}`);
    assert.equal(
      r.stderr,
      '--remove-hooks rewrites your ~/.claude/settings.json and needs a terminal to ask.\n' +
        'There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n' +
        '--yes to say yes in advance.\n',
    );
    assert.equal(r.stdout, '');
    assert.deepEqual(readFileSync(path), before, 'the CLI removed hooks it had refused to touch');
    assert.equal(backupsIn(path).length, backupsBefore, 'the refusal took a backup');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the real CLI --remove-hooks --yes removes and exits 0', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    assert.equal(runCli(['--install-hooks', '--yes'], root).status, 0);
    const r = runCli(['--remove-hooks', '--yes'], root);
    assert.equal(r.status, 0, `${r.stdout}${r.stderr}`);
    assert.deepEqual(readJson(join(root, '.claude', 'settings.json')).hooks, {});
    assert.ok(r.stderr.includes('bantamkit would remove 7 hook entries from '), r.stderr);
    assert.ok(r.stdout.startsWith('removed bantamkit hooks from '), r.stdout);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the real CLI --remove-hooks with nothing to remove exits 0 with no terminal', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    const r = runCli(['--remove-hooks'], root);
    assert.equal(r.status, 0, `${r.stdout}${r.stderr}`);
    assert.ok(r.stdout.startsWith('no bantamkit hooks are installed in '), r.stdout);
    assert.equal(r.stderr, '');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the real CLI refuses --yes without a flag it can consent to', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    const r = runCli(['--yes'], root);
    assert.equal(r.status, 1, `${r.stdout}${r.stderr}`);
    assert.equal(r.stderr, '--yes is only meaningful with --install-hooks or --remove-hooks\n');
    assert.equal(existsSync(join(root, '.claude')), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the three flags are in -h, with their ruled sentences', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    const r = runCli(['-h'], root);
    assert.equal(r.status, 0, r.stderr);
    const help = r.stdout.replace(/\s+/g, ' ');
    assert.ok(help.includes("--install-hooks add bantamkit's hook entries to ~/.claude/settings.json, then exit"), r.stdout);
    assert.ok(help.includes("--remove-hooks take bantamkit's hook entries back out of ~/.claude/settings.json, then exit"), r.stdout);
    assert.ok(
      help.includes('--yes with --install-hooks or --remove-hooks, say yes in advance instead of being asked'),
      r.stdout,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ------------------------------------------------ the one branch a seam cannot reach: a tty

/**
 * THE `ask` SEAM COVERS EVERY CASE ABOVE AND COVERS THE READER IN NONE OF THEM, and that gap
 * shipped a defect for the length of one build. `askAtTheTerminal` reads fd 0 synchronously;
 * Node leaves a TERMINAL's fd 0 non-blocking, so the first read throws `EAGAIN` before the
 * person has typed anything, and the first version of that function treated the throw as EOF
 * and answered "no". Every case above stayed green, because every case above hands the answer
 * in through `ask` and never reaches the reader at all.
 *
 * So this is driven through a REAL pty, and the only pty on this machine that a test can open
 * is CPython's. `python3` is a precondition, not a dependency of the product: skipped where it
 * is missing, and on Windows, which has no `pty` module.
 */
const PTY_DRIVER = `
import os, pty, select, sys, time
answer, home, cli = sys.argv[1], sys.argv[2], sys.argv[3]
flag = sys.argv[5]
pid, fd = pty.fork()
if pid == 0:
    os.environ['HOME'] = home
    os.environ['USERPROFILE'] = home
    os.execv(sys.argv[4], [sys.argv[4], cli, flag])
out, sent = b'', False
while True:
    ready, _, _ = select.select([fd], [], [], 15)
    if not ready:
        break
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
    out += chunk
    if not sent and b'[y/N]' in out:
        time.sleep(0.1)
        os.write(fd, answer.encode() + b'\\n')
        sent = True
_, status = os.waitpid(pid, 0)
sys.stdout.write(out.decode('utf8', 'replace'))
sys.stdout.write('\\nEXIT %d\\n' % os.waitstatus_to_exitcode(status))
`;

const havePython = process.platform !== 'win32' && spawnSync('python3', ['-c', 'import pty'], { encoding: 'utf8' }).status === 0;

function overAPty(answer, root, flag = '--install-hooks') {
  const driver = join(root, 'drive.py');
  writeFileSync(driver, PTY_DRIVER, 'utf8');
  const r = spawnSync('python3', [driver, answer, root, OWN_CLI, process.execPath, flag], { encoding: 'utf8' });
  assert.equal(r.status, 0, `the pty driver itself failed: ${r.stderr}`);
  return r.stdout;
}

for (const [answer, writes] of [
  ['y', true],
  ['Y', true],
  ['n', false],
  ['', false],
]) {
  test(`at a REAL terminal, answering ${JSON.stringify(answer)} ${writes ? 'writes' : 'writes nothing'}`, { skip: !havePython && 'python3 with a pty module is the only terminal a test can open here' }, () => {
    const root = mkdtempSync(join(tmpdir(), 'bk-hooks-pty-'));
    try {
      const path = join(root, '.claude', 'settings.json');
      const before = seed(path, `${JSON.stringify({ model: 'opus', hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
      const out = overAPty(answer, root);
      assert.ok(out.includes('Write these hook entries? [y/N]'), out);
      if (writes) {
        assert.ok(out.includes('\nEXIT 0\n'), out);
        assert.equal(Object.keys(readJson(path).hooks).length, 7, out);
        assert.deepEqual(readJson(path).hooks.PreToolUse[0], FOREIGN);
        assert.equal(readJson(path).model, 'opus');
      } else {
        assert.ok(out.includes('no hooks were written'), out);
        assert.ok(out.includes('\nEXIT 1\n'), out);
        assert.deepEqual(readFileSync(path), before, 'a terminal refusal wrote to the settings file');
        assert.deepEqual(backupsIn(path), [], 'a terminal refusal took a backup');
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

/*
 * AND THE SAME FOUR ANSWERS ON THE REMOVAL PATH. The reader is the same function, but the
 * QUESTION is not, and neither is the sentence a "no" produces — so a removal that reached a
 * terminal and then wrote anyway, or that printed the install's question, is only visible
 * here. The seam cases above cannot see either: they never reach `askAtTheTerminal` at all.
 */
for (const [answer, removes] of [
  ['y', true],
  ['Y', true],
  ['n', false],
  ['', false],
]) {
  test(`at a REAL terminal, --remove-hooks answered ${JSON.stringify(answer)} ${removes ? 'removes' : 'removes nothing'}`, { skip: !havePython && 'python3 with a pty module is the only terminal a test can open here' }, () => {
    const root = mkdtempSync(join(tmpdir(), 'bk-hooks-pty-'));
    try {
      const path = join(root, '.claude', 'settings.json');
      seed(path, `${JSON.stringify({ model: 'opus', hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
      assert.equal(runCli(['--install-hooks', '--yes'], root).status, 0);
      const before = readFileSync(path);
      const backupsBefore = backupsIn(path).length;
      const out = overAPty(answer, root, '--remove-hooks');
      assert.ok(out.includes('Remove these hook entries? [y/N]'), out);
      if (removes) {
        assert.ok(out.includes('\nEXIT 0\n'), out);
        assert.deepEqual(readJson(path).hooks, { PreToolUse: [FOREIGN] }, out);
        assert.equal(readJson(path).model, 'opus');
      } else {
        assert.ok(out.includes('no hooks were removed'), out);
        assert.ok(out.includes('\nEXIT 1\n'), out);
        assert.deepEqual(readFileSync(path), before, 'a terminal refusal removed hooks anyway');
        assert.equal(backupsIn(path).length, backupsBefore, 'a terminal refusal took a backup');
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

test('--mcp-report --install-hooks prints a report and writes no settings file', () => {
  // DISPATCH ORDER IS REGISTRATION ORDER, the rule every flag on this parser follows.
  const root = mkdtempSync(join(tmpdir(), 'bk-hooks-cli-'));
  try {
    const r = runCli(['--mcp-report', '--install-hooks', '--yes'], root);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(existsSync(join(root, '.claude', 'settings.json')), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
