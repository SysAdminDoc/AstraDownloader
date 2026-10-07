'use strict';

// pytest.ini leans on three plugins (xdist for `-n auto`, pytest-qt for
// qt_api, pytest-asyncio for its loop-scope key), and for a long time none of
// them was declared anywhere: a clean environment got the app requirements,
// ran pytest and died on "unrecognized arguments: -n". The PEP 735 `test`
// group in pyproject.toml is the declaration. This gate keeps the two files
// in step, so pytest.ini can't start relying on a plugin nobody installs.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');

// Ini keys pytest itself defines (pytest 9, read off `pytest --help` with
// plugin autoload disabled). Anything else in pytest.ini belongs to a plugin.
const CORE_INI_KEYS = new Set([
    'addopts', 'assertion_text_diff_style', 'cache_dir', 'collect_imported_tests',
    'consider_namespace_packages', 'console_output_style',
    'disable_test_id_escaping_and_forfeit_all_rights_to_community_support',
    'doctest_encoding', 'doctest_optionflags', 'empty_parameter_set_mark',
    'enable_assertion_pass_hook', 'faulthandler_exit_on_timeout', 'faulthandler_timeout',
    'filterwarnings', 'junit_duration_report', 'junit_family', 'junit_log_passing_tests',
    'junit_logging', 'junit_suite_name', 'log_auto_indent', 'log_cli', 'log_cli_date_format',
    'log_cli_format', 'log_cli_level', 'log_date_format', 'log_file', 'log_file_date_format',
    'log_file_format', 'log_file_level', 'log_file_mode', 'log_format', 'log_level',
    'markers', 'max_warnings', 'minversion', 'norecursedirs', 'python_classes',
    'python_files', 'python_functions', 'pythonpath', 'required_plugins', 'strict',
    'strict_config', 'strict_markers', 'strict_parametrization_ids', 'strict_xfail',
    'testpaths', 'tmp_path_retention_count', 'tmp_path_retention_policy',
    'truncation_limit_chars', 'truncation_limit_lines', 'usefixtures',
    'verbosity_assertions', 'verbosity_subtests', 'verbosity_test_cases',
]);

// What each plugin distribution adds to pytest.ini's vocabulary: `-p` names,
// ini keys and command-line flags. A plugin missing from this table is caught
// anyway, as an ini key or `-p` name nothing here or in core accounts for.
const PLUGINS = [
    {
        distribution: 'pytest-xdist',
        modules: ['xdist', 'xdist.plugin', 'xdist.looponfail'],
        iniKeys: ['rsyncdirs', 'rsyncignore', 'looponfailroots'],
        flags: [
            '-n', '--numprocesses', '--maxprocesses', '--max-worker-restart', '--dist',
            '-d', '--tx', '--px', '--rsyncdir', '--rsyncignore', '-f', '--looponfail',
            '--maxschedchunk', '--loadscope-reorder', '--no-loadscope-reorder',
        ],
    },
    {
        distribution: 'pytest-qt',
        modules: ['pytestqt', 'pytestqt.plugin'],
        iniPrefix: 'qt_',
        flagPrefix: '--qt-',
        flags: ['--no-qt-log'],
    },
    {
        distribution: 'pytest-asyncio',
        modules: ['asyncio', 'pytest_asyncio', 'pytest_asyncio.plugin'],
        iniPrefix: 'asyncio_',
        flagPrefix: '--asyncio-',
    },
    {
        distribution: 'pytest-timeout',
        modules: ['timeout', 'pytest_timeout'],
        iniKeys: [
            'timeout', 'timeout_method', 'timeout_func_only',
            'timeout_disable_debugger_detection', 'session_timeout',
        ],
        flags: ['--timeout', '--timeout-method', '--session-timeout', '--timeout-disable-debugger-detection'],
    },
    {
        distribution: 'pytest-cov',
        modules: ['pytest_cov', 'pytest_cov.plugin'],
        flagPrefix: '--cov',
        flags: ['--no-cov', '--no-cov-on-fail'],
    },
];

function normalizeName(name) {
    return String(name).trim().toLowerCase().replace(/[-_.]+/g, '-');
}

function iniSettings(text, section = 'pytest') {
    const settings = new Map();
    let current = null;
    let key = null;
    for (const raw of String(text).split(/\r?\n/)) {
        if (/^\s*[#;]/.test(raw) || !raw.trim()) continue;
        const header = /^\[([^\]]+)\]\s*$/.exec(raw);
        if (header) {
            current = header[1].trim();
            key = null;
            continue;
        }
        if (current !== section) continue;
        if (/^\s/.test(raw) && key) {
            settings.set(key, `${settings.get(key)}\n${raw.trim()}`);
            continue;
        }
        const pair = /^([A-Za-z0-9_.-]+)\s*[=:]\s*(.*)$/.exec(raw);
        if (pair) {
            key = pair[1];
            settings.set(key, pair[2].trim());
        }
    }
    return settings;
}

// Just enough TOML for one [dependency-groups] table: string requirements and
// `{ include-group = "..." }` tables, as PEP 735 defines them.
function dependencyGroup(pyprojectText, name, seen = new Set()) {
    const table = /^\[dependency-groups\][ \t]*$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(pyprojectText);
    if (!table) return null;
    const entry = new RegExp(`^${name.replace(/[-]/g, '[-_.]')}\\s*=\\s*\\[([\\s\\S]*?)\\]`, 'm')
        .exec(table[1].replace(/#.*$/gm, ''));
    if (!entry) return null;
    seen.add(name);
    const declared = new Set();
    for (const match of entry[1].matchAll(/\{[^}]*include-group\s*=\s*"([^"]+)"[^}]*\}|"([^"]+)"/g)) {
        if (match[1]) {
            if (seen.has(match[1])) continue;
            for (const included of dependencyGroup(pyprojectText, match[1], seen) || []) declared.add(included);
            continue;
        }
        declared.add(normalizeName(/^[A-Za-z0-9_.-]+/.exec(match[2].trim())[0]));
    }
    return declared;
}

function addoptsTokens(value) {
    return String(value || '').split(/\s+/).filter(Boolean).map((token) => token.replace(/^["']|["']$/g, ''));
}

function pluginForFlag(flag) {
    return PLUGINS.find((plugin) => (plugin.flags || []).includes(flag) ||
        (plugin.flagPrefix && flag.startsWith(plugin.flagPrefix)));
}

function pluginForIniKey(key) {
    return PLUGINS.find((plugin) => (plugin.iniKeys || []).includes(key) ||
        (plugin.iniPrefix && key.startsWith(plugin.iniPrefix)));
}

// Every way pytest.ini can depend on a plugin, each mapped to the
// distribution that provides it. `-p no:name` disables and needs nothing.
function requiredDistributions(iniText) {
    const settings = iniSettings(iniText);
    const needs = [];
    const problems = [];
    for (const key of settings.keys()) {
        if (CORE_INI_KEYS.has(key)) continue;
        const plugin = pluginForIniKey(key);
        if (plugin) needs.push({ distribution: plugin.distribution, via: `ini key ${key}` });
        else problems.push(`pytest.ini sets ${key}, which neither pytest nor a known plugin defines; map it in this test`);
    }
    for (const distribution of String(settings.get('required_plugins') || '').split(/\s+/).filter(Boolean)) {
        const name = /^[A-Za-z0-9_.-]+/.exec(distribution);
        if (name) needs.push({ distribution: name[0], via: `required_plugins ${distribution}` });
    }
    const tokens = addoptsTokens(settings.get('addopts'));
    for (let index = 0; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (token === '-p' || (token.startsWith('-p') && !token.startsWith('--'))) {
            const name = token === '-p' ? tokens[++index] : token.slice(2);
            if (!name || name.startsWith('no:')) continue;
            const plugin = PLUGINS.find((candidate) => candidate.modules.includes(name));
            if (plugin) needs.push({ distribution: plugin.distribution, via: `-p ${name}` });
            else problems.push(`pytest.ini loads plugin ${name} with -p, and no distribution is mapped for it; map it in this test`);
            continue;
        }
        let flag = null;
        if (token.startsWith('--')) flag = token.split('=')[0];
        else if (/^-[A-Za-z]/.test(token)) flag = token.slice(0, 2);
        if (!flag) continue;
        const plugin = pluginForFlag(flag);
        if (plugin) needs.push({ distribution: plugin.distribution, via: `addopts ${flag}` });
    }
    needs.push({ distribution: 'pytest', via: 'the suite itself' });
    return { needs, problems };
}

function undeclaredPlugins(iniText, pyprojectText, group = 'test') {
    const declared = dependencyGroup(pyprojectText, group);
    if (!declared) return [`pyproject.toml has no [dependency-groups] ${group} group`];
    const { needs, problems } = requiredDistributions(iniText);
    const missing = needs
        .filter(({ distribution }) => !declared.has(normalizeName(distribution)))
        .map(({ distribution, via }) =>
            `pytest.ini needs ${distribution} (${via}), which the ${group} group does not declare`);
    return [...problems, ...missing];
}

const pytestIni = fs.readFileSync(path.join(repoRoot, 'pytest.ini'), 'utf8');
const pyproject = fs.readFileSync(path.join(repoRoot, 'pyproject.toml'), 'utf8');

test('every plugin pytest.ini relies on is declared in the test dependency group', () => {
    assert.deepEqual(undeclaredPlugins(pytestIni, pyproject), []);
    const declared = dependencyGroup(pyproject, 'test');
    for (const name of ['pytest', 'pytest-xdist', 'pytest-qt', 'pytest-asyncio']) {
        assert.ok(declared.has(name), `the test group must declare ${name}`);
    }
    assert.doesNotMatch(pyproject, /^\[(build-system|project)\]/m,
        'pyproject.toml carries tooling only; build.py and requirements.txt own the app');
});

test('the toolchain gate names a plugin pytest.ini uses but the group omits', () => {
    const withoutQt = pyproject.replace(/^\s*"pytest-qt[^"]*",?\s*$/m, '');
    assert.notEqual(withoutQt, pyproject, 'the fixture must actually drop pytest-qt');
    assert.match(undeclaredPlugins(pytestIni, withoutQt).join('\n'), /pytest-qt \(ini key qt_api\)/);

    const withoutXdist = pyproject.replace(/^\s*"pytest-xdist[^"]*",?\s*$/m, '');
    assert.match(undeclaredPlugins(pytestIni, withoutXdist).join('\n'), /pytest-xdist \(addopts -n\)/);

    const plantedFlag = pytestIni.replace(/^addopts = (.*)$/m, 'addopts = $1 --timeout=60');
    assert.match(undeclaredPlugins(plantedFlag, pyproject).join('\n'), /pytest-timeout \(addopts --timeout\)/);

    const plantedPlugin = pytestIni.replace(/^addopts = (.*)$/m, 'addopts = $1 -p pytest_randomly');
    assert.match(undeclaredPlugins(plantedPlugin, pyproject).join('\n'), /loads plugin pytest_randomly/);

    const plantedKey = `${pytestIni}\nrandomly_seed = 1\n`;
    assert.match(undeclaredPlugins(plantedKey, pyproject).join('\n'), /sets randomly_seed/);

    const disabled = pytestIni.replace(/^addopts = (.*)$/m, 'addopts = $1 -p no:randomly');
    assert.deepEqual(undeclaredPlugins(disabled, pyproject), [], '-p no:name disables a plugin and needs nothing');
});
