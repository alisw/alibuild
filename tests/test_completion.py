"""Tests for the shell completion files.

Validates that the completion scripts match the actual CLI options
defined in alibuild_helpers/args.py and the alienv script.
"""

import os
import re
import subprocess
import sys
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
COMPLETION_DIR = os.path.realpath(
    os.path.join(REPO_ROOT, "alibuild_helpers", "completions")
)
ZSH_COMPLETION_FILE = os.path.join(COMPLETION_DIR, "zsh.sh")
BASH_COMPLETION_FILE = os.path.join(COMPLETION_DIR, "bash.sh")
ARGS_FILE = os.path.join(REPO_ROOT, "alibuild_helpers", "args.py")
ALIENV_FILE = os.path.join(REPO_ROOT, "alienv")


def read_file(path):
    with open(path) as f:
        return f.read()


def extract_long_options_from_completion(text, function_name):
    """Extract all --long-option names from a zsh completion function."""
    # Find the function body
    pattern = re.compile(
        r"^" + re.escape(function_name) + r"\(\)\s*\{(.*?)^\}",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return set()
    body = match.group(1)
    # Match all --option-name patterns (the actual option, not descriptions)
    options = set()
    for m in re.finditer(r"'[^']*?--([a-z][-a-z0-9]*)", body):
        options.add("--" + m.group(1))
    # Also match unquoted --options in _arguments lines
    for m in re.finditer(r'"[^"]*?--([a-z][-a-z0-9]*)', body):
        options.add("--" + m.group(1))
    return options


def extract_long_options_from_bash(text, function_name):
    """Extract all --long-option names from a bash completion function."""
    pattern = re.compile(
        r"^" + re.escape(function_name) + r"\(\)\s*\{(.*?)^\}",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return set()
    body = match.group(1)
    options = set()
    for m in re.finditer(r"(--[a-z][-a-z0-9]*)", body):
        options.add(m.group(1))
    return options


def extract_long_options_from_argparse(text, parser_prefix):
    """Extract all --long-option names added to a given parser in args.py."""
    options = set()
    # Match add_argument calls on the given parser (or its groups)
    # e.g. build_parser.add_argument("--foo", ...)
    #      build_docker.add_argument("--foo", ...)
    for m in re.finditer(
        r'\.add_argument\([^)]*"(--[a-z][-a-z0-9]*)"', text
    ):
        # Check that this belongs to the right parser by looking at the
        # variable name prefix on the same line
        line_start = text.rfind("\n", 0, m.start()) + 1
        line = text[line_start : m.end()]
        if line.lstrip().startswith(parser_prefix):
            options.add(m.group(1))
    return options


def extract_subcommands_from_completion(text, function_name):
    """Extract subcommand names from a completion function's commands array."""
    pattern = re.compile(
        r"^" + re.escape(function_name) + r"\(\)\s*\{(.*?)^\}",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return set()
    body = match.group(1)
    commands = set()
    for m in re.finditer(r"'(\w[\w-]*):", body):
        commands.add(m.group(1))
    return commands


def extract_alienv_actions_from_script(text):
    """Extract action names from the alienv bash 'case "$ACTION"' block."""
    actions = set()
    in_case = False
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if 'case "$ACTION"' in stripped:
            in_case = True
            depth = 1
            continue
        if in_case:
            # Track nested case/esac to avoid stopping at inner esac
            if re.match(r"^case\b", stripped):
                depth += 1
            elif stripped == "esac":
                depth -= 1
                if depth == 0:
                    break
                continue
            # Only match top-level patterns (depth == 1)
            if depth == 1:
                m = re.match(r"^([\w|']+)\)", stripped)
                if m:
                    for action in m.group(1).split("|"):
                        action = action.strip().strip("'")
                        # Skip empty-string and wildcard catch-all patterns
                        if action and action not in ("", "*"):
                            actions.add(action)
    return actions


class TestZshCompletion(unittest.TestCase):
    """Validate zsh completion file against actual CLI definitions."""

    @classmethod
    def setUpClass(cls):
        cls.completion = read_file(ZSH_COMPLETION_FILE)
        cls.args_source = read_file(ARGS_FILE)
        cls.alienv_source = read_file(ALIENV_FILE)

    def test_compdef_lists_all_commands(self):
        """The #compdef line must list all supported commands."""
        first_line = self.completion.splitlines()[0]
        for cmd in ("aliBuild", "alienv"):
            self.assertIn(cmd, first_line,
                          f"{cmd} missing from #compdef line")

    def test_dispatch_uses_service_variable(self):
        """The bottom of the file must dispatch based on $service."""
        self.assertIn('case "$service"', self.completion,
                      "Completion file must dispatch based on $service")
        for cmd, func in [("aliBuild", "_aliBuild"),
                          ("alienv", "_alienv")]:
            pattern = re.compile(
                r"\b" + re.escape(cmd) + r"[)|].*" + re.escape(func),
            )
            self.assertTrue(
                pattern.search(self.completion),
                f"$service dispatch missing mapping {cmd} -> {func}",
            )

    def test_build_options_match(self):
        """All build subcommand --options in args.py must be in completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "build"
        )
        completion_opts = extract_long_options_from_completion(
            self.completion, "_aliBuild_cmd_build"
        )
        missing = argparse_opts - completion_opts
        self.assertFalse(missing,
                         f"Build options in args.py missing from completion: {missing}")

    def test_clean_options_match(self):
        """All clean subcommand --options in args.py must be in completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "clean"
        )
        completion_opts = extract_long_options_from_completion(
            self.completion, "_aliBuild_cmd_clean"
        )
        missing = argparse_opts - completion_opts
        self.assertFalse(missing,
                         f"Clean options in args.py missing from completion: {missing}")

    def test_deps_options_match(self):
        """All deps subcommand --options in args.py must be in completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "deps"
        )
        completion_opts = extract_long_options_from_completion(
            self.completion, "_aliBuild_cmd_deps"
        )
        missing = argparse_opts - completion_opts
        self.assertFalse(missing,
                         f"Deps options in args.py missing from completion: {missing}")

    def test_doctor_options_match(self):
        """All doctor subcommand --options in args.py must be in completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "doctor"
        )
        completion_opts = extract_long_options_from_completion(
            self.completion, "_aliBuild_cmd_doctor"
        )
        missing = argparse_opts - completion_opts
        self.assertFalse(missing,
                         f"Doctor options in args.py missing from completion: {missing}")

    def test_init_options_match(self):
        """All init subcommand --options in args.py must be in completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "init"
        )
        completion_opts = extract_long_options_from_completion(
            self.completion, "_aliBuild_cmd_init"
        )
        missing = argparse_opts - completion_opts
        self.assertFalse(missing,
                         f"Init options in args.py missing from completion: {missing}")

    def test_version_options_match(self):
        """All version subcommand --options in args.py must be in completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "version"
        )
        completion_opts = extract_long_options_from_completion(
            self.completion, "_aliBuild_cmd_version"
        )
        missing = argparse_opts - completion_opts
        self.assertFalse(missing,
                         f"Version options in args.py missing from completion: {missing}")

    def test_alibuild_subcommands_match(self):
        """aliBuild subcommands in completion must match args.py subparsers."""
        # Subcommands defined in args.py via add_subparser
        argparse_cmds = set()
        for m in re.finditer(
            r'subparsers\.add_parser\(\s*"(\w+)"', self.args_source
        ):
            argparse_cmds.add(m.group(1))
        completion_cmds = extract_subcommands_from_completion(
            self.completion, "_aliBuild"
        )
        missing = argparse_cmds - completion_cmds
        self.assertFalse(missing,
                         f"Subcommands in args.py missing from completion: {missing}")

    def test_alienv_subcommands_match(self):
        """alienv completion subcommands must match the alienv script."""
        script_actions = extract_alienv_actions_from_script(self.alienv_source)
        completion_cmds = extract_subcommands_from_completion(
            self.completion, "_alienv"
        )
        # The script has '' (empty) and * (wildcard) cases we skip.
        # 'help' is both a --help flag and a subcommand.
        missing = script_actions - completion_cmds
        self.assertFalse(missing,
                         f"alienv actions missing from completion: {missing}")


class TestBashCompletion(unittest.TestCase):
    """Validate bash completion file against actual CLI definitions."""

    @classmethod
    def setUpClass(cls):
        cls.completion = read_file(BASH_COMPLETION_FILE)
        cls.args_source = read_file(ARGS_FILE)
        cls.alienv_source = read_file(ALIENV_FILE)

    def test_build_options_match(self):
        """All build --options in args.py must appear in bash completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "build"
        )
        bash_opts = extract_long_options_from_bash(
            self.completion, "_aliBuild_complete"
        )
        missing = argparse_opts - bash_opts
        self.assertFalse(missing,
                         f"Build options in args.py missing from bash completion: {missing}")

    def test_clean_options_match(self):
        """All clean --options in args.py must appear in bash completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "clean"
        )
        bash_opts = extract_long_options_from_bash(
            self.completion, "_aliBuild_complete"
        )
        missing = argparse_opts - bash_opts
        self.assertFalse(missing,
                         f"Clean options in args.py missing from bash completion: {missing}")

    def test_deps_options_match(self):
        """All deps --options in args.py must appear in bash completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "deps"
        )
        bash_opts = extract_long_options_from_bash(
            self.completion, "_aliBuild_complete"
        )
        missing = argparse_opts - bash_opts
        self.assertFalse(missing,
                         f"Deps options in args.py missing from bash completion: {missing}")

    def test_doctor_options_match(self):
        """All doctor --options in args.py must appear in bash completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "doctor"
        )
        bash_opts = extract_long_options_from_bash(
            self.completion, "_aliBuild_complete"
        )
        missing = argparse_opts - bash_opts
        self.assertFalse(missing,
                         f"Doctor options in args.py missing from bash completion: {missing}")

    def test_init_options_match(self):
        """All init --options in args.py must appear in bash completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "init"
        )
        bash_opts = extract_long_options_from_bash(
            self.completion, "_aliBuild_complete"
        )
        missing = argparse_opts - bash_opts
        self.assertFalse(missing,
                         f"Init options in args.py missing from bash completion: {missing}")

    def test_version_options_match(self):
        """All version --options in args.py must appear in bash completion."""
        argparse_opts = extract_long_options_from_argparse(
            self.args_source, "version"
        )
        bash_opts = extract_long_options_from_bash(
            self.completion, "_aliBuild_complete"
        )
        missing = argparse_opts - bash_opts
        self.assertFalse(missing,
                         f"Version options in args.py missing from bash completion: {missing}")

    def test_registers_all_commands(self):
        """The bash completion must register aliBuild and alienv."""
        for cmd in ("aliBuild", "alienv"):
            self.assertRegex(
                self.completion,
                r"complete\s+-F\s+\w+\s+" + re.escape(cmd),
                f"Missing 'complete' registration for {cmd}",
            )

    def test_alibuild_subcommands_present(self):
        """All subcommands from args.py must appear in bash completion."""
        argparse_cmds = set()
        for m in re.finditer(
            r'subparsers\.add_parser\(\s*"(\w+)"', self.args_source
        ):
            argparse_cmds.add(m.group(1))
        # All subcommands should appear somewhere in the bash completion
        for cmd in argparse_cmds:
            self.assertIn(cmd, self.completion,
                          f"Subcommand '{cmd}' missing from bash completion")


class TestCompletionIntegration(unittest.TestCase):
    """Integration tests: run aliBuild completion {bash,zsh} via subprocess."""

    def test_completion_bash(self):
        """aliBuild completion bash prints bash completion to stdout."""
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "aliBuild"), "completion", "bash"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("complete -F", result.stdout)
        self.assertIn("_aliBuild_complete", result.stdout)

    def test_completion_zsh(self):
        """aliBuild completion zsh prints zsh completion to stdout."""
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "aliBuild"), "completion", "zsh"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("#compdef", result.stdout)
        self.assertIn("_aliBuild", result.stdout)


if __name__ == "__main__":
    unittest.main()
