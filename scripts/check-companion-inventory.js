#!/usr/bin/env node
'use strict';

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const {
    buildCompanionInventory,
    COMPANION_EXE_NAME,
    inspectCompanionInventory
} = require('./companion-license-inventory');

const REPO_ROOT = path.join(__dirname, '..');
const BUILD_DIR = path.join(REPO_ROOT, 'build');

function sha256(filePath) {
    return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function checkCompanionInventory(inventory, artifactSha256) {
    if (!inventory.components.length || !inventory.dependencies.length) {
        throw new Error('staged companion inventory is empty');
    }
    const inspection = inspectCompanionInventory(inventory, artifactSha256);
    if (inspection.issues.length) {
        throw new Error(
            `companion license inspection failed with ${inspection.issues.length} issue(s):\n` +
            inspection.issues.map((issue) => `- ${issue}`).join('\n')
        );
    }
    return inspection;
}

function main() {
    const exePath = path.join(BUILD_DIR, COMPANION_EXE_NAME);
    const inventory = buildCompanionInventory(REPO_ROOT, BUILD_DIR);
    const artifactSha256 = sha256(exePath);
    const inspection = checkCompanionInventory(inventory, artifactSha256);
    console.log(
        `Companion inventory: ${inventory.components.length} components; ` +
        `${inspection.components.length} release-scoped components; ` +
        `${inventory.dependencies.length} dependency edges; SHA-256 ${artifactSha256}`
    );
}

if (require.main === module) {
    try {
        main();
    } catch (error) {
        console.error(`[check-companion-inventory] ${error.message}`);
        process.exitCode = 1;
    }
}

module.exports = { checkCompanionInventory };
