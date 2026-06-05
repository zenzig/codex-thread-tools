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
  ["handoff-marker", "codex-thread-handoff-marker.py"],
  ["visual-archive", "codex-visual-archive.py"],
  ["recover", "recover-codex-thread-starter.py"],
]);

const HELP = `codex-thread-tools ${VERSION}

Usage:
  codex-thread-tools health [args...]
  codex-thread-tools handoff-marker [args...]
  codex-thread-tools visual-archive [args...]
  codex-thread-tools recover [args...]
  codex-thread-tools install-skill
  codex-thread-tools --version

Examples:
  codex-thread-tools health
  codex-thread-tools health check ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
  codex-thread-tools visual-archive scan ~/.codex/sessions/YYYY/MM/DD/thread.jsonl
`;

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
    return installSkill();
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

function installSkill() {
  const codexHome = path.join(os.homedir(), ".codex");
  if (!fs.existsSync(codexHome)) {
    process.stderr.write("Open Codex once so ~/.codex exists, then retry.\n");
    return 1;
  }
  const skillsDir = path.join(codexHome, "skills");
  if (!fs.existsSync(skillsDir)) {
    fs.mkdirSync(skillsDir);
  }
  const source = path.join(ROOT, "skills", "codex-thread-handoff");
  const target = path.join(skillsDir, "codex-thread-handoff");
  fs.rmSync(target, { recursive: true, force: true });
  fs.cpSync(source, target, { recursive: true });
  process.stdout.write(`Installed codex-thread-handoff to ${target}\n`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));
