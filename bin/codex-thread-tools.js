#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const VERSION = fs.readFileSync(path.join(ROOT, "VERSION"), "utf8").trim();

const PYTHON_TOOLS = new Map([
  ["health", "codex-thread-health.py"],
  ["handoff-summary", "codex-thread-handoff-summary.py"],
  ["handoff-marker", "codex-thread-handoff-marker.py"],
  ["session-archive", "codex-session-archive.py"],
  ["visual-archive", "codex-visual-archive.py"],
  ["recover", "recover-codex-thread-starter.py"],
]);

const HELP = `codex-thread-tools ${VERSION}

Usage:
  codex-thread-tools health [args...]
  codex-thread-tools handoff-summary [args...]
  codex-thread-tools handoff-marker [args...]
  codex-thread-tools session-archive [args...]
  codex-thread-tools visual-archive [args...]
  codex-thread-tools recover [args...]
  codex-thread-tools install-skill [--agent codex|claude]
  codex-thread-tools --version

Examples:
  codex-thread-tools health
  codex-thread-tools health --agent claude
  codex-thread-tools health check ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
  codex-thread-tools handoff-summary ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
  codex-thread-tools session-archive plan --older-than 30d --min-size 100MiB
  codex-thread-tools visual-archive scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
`;

const SAFE_SKILL_INVOCATION = [
  "Use the installed `codex-thread-handoff` skill to create a repository-backed",
  "handoff for a new task. Do not use Codex's native Handoff or `handoff_thread`.",
  "If the skill is unavailable, stop and report that it must be installed.",
].join("\n");

function main(argv) {
  const [command, ...args] = argv;
  if (!command || command === "help" || command === "--help" || command === "-h") {
    process.stdout.write(HELP);
    return 0;
  }
  if (command === "--version" || command === "-v" || command === "version") {
    process.stdout.write(`${VERSION}\n`);
    return 0;
  }
  if (command === "install-skill") {
    return skillAgent(args) === "claude" ? installClaudeSkill() : installSkill();
  }
  if (PYTHON_TOOLS.has(command)) {
    return runPythonTool(PYTHON_TOOLS.get(command), args);
  }
  process.stderr.write(`Unknown command: ${command}\n\n${HELP}`);
  return 1;
}

function runPythonTool(toolName, args) {
  const script = path.join(ROOT, "tools", toolName);
  for (const python of pythonCommands()) {
    const command = python.command;
    const pythonArgs = [...python.args, script, ...args];
    const result = spawnSync(command, pythonArgs, {
      cwd: ROOT,
      stdio: "inherit",
      env: process.env,
    });
    if (result.error && result.error.code === "ENOENT") {
      continue;
    }
    if (result.error) {
      process.stderr.write(`${result.error.message}\n`);
      return 1;
    }
    return result.status === null ? 1 : result.status;
  }
  process.stderr.write(
    "Python 3 is required. Install Python 3, then retry this command.\n"
  );
  return 1;
}

function pythonCommands() {
  if (process.platform === "win32") {
    return [
      { command: "py", args: ["-3"] },
      { command: "python", args: [] },
      { command: "python3", args: [] },
    ];
  }
  return [
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ];
}

function skillAgent(args) {
  const index = args.indexOf("--agent");
  if (index !== -1 && args[index + 1]) {
    return args[index + 1];
  }
  const hasCodex = fs.existsSync(path.join(os.homedir(), ".codex"));
  const hasClaude = fs.existsSync(path.join(os.homedir(), ".claude"));
  return !hasCodex && hasClaude ? "claude" : "codex";
}

function installClaudeSkill() {
  const claudeHome = path.join(os.homedir(), ".claude");
  if (!fs.existsSync(claudeHome)) {
    process.stderr.write("Open Claude Code once so ~/.claude exists, then retry.\n");
    return 1;
  }
  try {
    const source = path.join(ROOT, "skills", "thread-handoff");
    const target = path.join(claudeHome, "skills", "thread-handoff");
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.rmSync(target, { recursive: true, force: true });
    fs.cpSync(source, target, { recursive: true });
    process.stdout.write(
      `Installed thread-handoff to ${target}\n\n` +
        "Invoke it in Claude Code with: /thread-handoff\n" +
        "Check session health with: codex-thread-tools health --agent claude\n"
    );
    return 0;
  } catch (error) {
    process.stderr.write(`Failed to install thread-handoff: ${error.message}\n`);
    return 1;
  }
}

function installSkill() {
  const codexHome = path.join(os.homedir(), ".codex");
  if (!fs.existsSync(codexHome)) {
    process.stderr.write("Open Codex once so ~/.codex exists, then retry.\n");
    return 1;
  }
  const skillsDir = path.join(codexHome, "skills");

  try {
    fs.mkdirSync(skillsDir, { recursive: true });
    const source = path.join(ROOT, "skills", "codex-thread-handoff");
    const sourceSkill = path.join(source, "SKILL.md");
    const target = path.join(skillsDir, "codex-thread-handoff");
    const targetSkill = path.join(target, "SKILL.md");

    fs.rmSync(target, { recursive: true, force: true });
    fs.cpSync(source, target, { recursive: true });

    const sourceSkillContents = fs.readFileSync(sourceSkill);
    const targetSkillContents = fs.readFileSync(targetSkill);
    if (!sourceSkillContents.equals(targetSkillContents)) {
      process.stderr.write(
        "Failed to install codex-thread-handoff: SKILL.md verification failed\n"
      );
      return 1;
    }

    process.stdout.write(
      `Installed codex-thread-handoff to ${target}\n\n` +
        "Invoke it with:\n" +
        `${SAFE_SKILL_INVOCATION}\n\n` +
        "After upgrading codex-thread-tools, rerun `codex-thread-tools install-skill` to refresh the copied skill.\n" +
        "If the updated skill is not visible, reload Codex or start a new task.\n"
    );
    return 0;
  } catch (error) {
    process.stderr.write(
      `Failed to install codex-thread-handoff: ${error.message}\n`
    );
    return 1;
  }
}

process.exitCode = main(process.argv.slice(2));
