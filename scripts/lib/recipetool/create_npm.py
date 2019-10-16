# Copyright (C) 2016 Intel Corporation
# Copyright (C) 2019 Savoir-Faire Linux
#
# SPDX-License-Identifier: GPL-2.0-only
#
"""
    Recipe creation tool - npm module support plugin
"""

import json
import os
import re
import shutil
import sys
import tempfile
import bb
from bb.fetch2 import runfetchcmd
from recipetool.create import RecipeHandler

tinfoil = None

def tinfoil_init(instance):
    """
        Initialize tinfoil.
    """
    global tinfoil
    tinfoil = instance

class NpmRecipeHandler(RecipeHandler):
    """
        Class to handle the npm recipe creation
    """

    @staticmethod
    def _get_registry(extravalues, lines_before):
        """
            Get the registry value from the '--npm-registry' option
            or the 'npm://registry' url.
        """
        registry_option = extravalues.get("NPM_REGISTRY")

        registry_fetch = None

        def handle_metadata(name, value, *unused):
            if name == "SRC_URI":
                for uri in value.split():
                    if uri.startswith("npm://"):
                        nonlocal registry_fetch
                        registry_fetch = re.sub(r"^npm://", "http://", uri.split(";")[0])
            return value, None, 0, True

        bb.utils.edit_metadata(lines_before, ["SRC_URI"], handle_metadata)

        if registry_fetch is not None:
            registry = registry_fetch

            if registry_option is not None:
                bb.warn("The npm registry is specified multiple times")
                bb.note("Using registry from the fetch url: '{}'".format(registry))
                extravalues.pop("NPM_REGISTRY", None)

        elif registry_option is not None:
            registry = registry_option

        else:
            registry = "http://registry.npmjs.org"

        return registry

    @staticmethod
    def _ensure_npm(d):
        """
            Check if the 'npm' command is available in the recipes, then build
            it and add it to the PATH.
        """
        if not tinfoil.recipes_parsed:
            tinfoil.parse_recipes()

        try:
            rd = tinfoil.parse_recipe('nodejs-native')
        except bb.providers.NoProvider:
            bb.error("Nothing provides 'nodejs-native' which is required for the build")
            bb.note("You will likely need to add a layer that provides nodejs")
            sys.exit(14)

        bindir = rd.getVar('STAGING_BINDIR_NATIVE')
        npmpath = os.path.join(bindir, 'npm')

        if not os.path.exists(npmpath):
            tinfoil.build_targets('nodejs-native', 'addto_recipe_sysroot')

            if not os.path.exists(npmpath):
                bb.error("Failed to add 'npm' to sysroot")
                sys.exit(14)

        d.prependVar("PATH", "{}:".format(bindir))

    @staticmethod
    def _run_npm_install(d, development):
        """
            Run the 'npm install' command without building the addons (if any).
            This is only needed to generate the initial shrinkwrap file.
            The 'node_modules' directory is created and populated.
        """
        cmd = "npm install"
        cmd += " --ignore-scripts"
        cmd += " --no-shrinkwrap"
        cmd += d.expand(" --cache=${NPM_CACHE_DIR}")
        cmd += d.expand(" --registry=${NPM_REGISTRY}")

        if development is None:
            cmd += " --production"

        bb.utils.remove(os.path.join(d.getVar("S"), "node_modules"), recurse=True)
        runfetchcmd(cmd, d, workdir=d.getVar("S"))
        bb.utils.remove(d.getVar("NPM_CACHE_DIR"), recurse=True)

    @staticmethod
    def _run_npm_shrinkwrap(d, development):
        """
            Run the 'npm shrinkwrap' command to generate the shrinkwrap file.
        """
        cmd = "npm shrinkwrap"

        if development is not None:
            cmd += " --development"

        runfetchcmd(cmd, d, workdir=d.getVar("S"))

    def _generate_shrinkwrap(self, d, lines, extravalues, development):
        """
            Check and generate the npm-shrinkwrap.json file if needed.
        """
        self._ensure_npm(d)
        self._run_npm_install(d, development)

        # Check if a shinkwrap file is already in the source
        src_shrinkwrap = os.path.join(d.getVar("S"), "npm-shrinkwrap.json")
        if os.path.exists(src_shrinkwrap):
            bb.note("Using the npm-shrinkwrap.json provided in the sources")
            return src_shrinkwrap

        # Generate the 'npm-shrinkwrap.json' file
        self._run_npm_shrinkwrap(d, development)

        # Convert the shrinkwrap file and save it in a temporary location
        tmpdir = tempfile.mkdtemp(prefix="recipetool-npm")
        tmp_shrinkwrap = os.path.join(tmpdir, "npm-shrinkwrap.json")
        shutil.move(src_shrinkwrap, tmp_shrinkwrap)

        # Add the shrinkwrap file as 'extrafiles'
        extravalues.setdefault("extrafiles", {})
        extravalues["extrafiles"]["npm-shrinkwrap.json"] = tmp_shrinkwrap

        # Add a line in the recipe to handle the shrinkwrap file
        lines.append("NPM_SHRINKWRAP = \"${THISDIR}/${BPN}/npm-shrinkwrap.json\"")

        # Clean the source tree
        bb.utils.remove(os.path.join(d.getVar("S"), "node_modules"), recurse=True)
        bb.utils.remove(src_shrinkwrap)

        return tmp_shrinkwrap

    @staticmethod
    def _name_from_npm(npm_name, number=False):
        """
            Generate a name based on the npm package name.
        """
        name = npm_name
        name = re.sub("/", "-", name)
        name = name.lower()
        if not number:
            name = re.sub(r"[^\-a-z]", "", name)
        else:
            name = re.sub(r"[^\-a-z0-9]", "", name)
        name = name.strip("-")
        return name

    def process(self, srctree, classes, lines_before, lines_after, handled, extravalues):
        """
            Handle the npm recipe creation
        """

        if 'buildsystem' in handled:
            return False

        files = RecipeHandler.checkfiles(srctree, ["package.json"])

        if not files:
            return False

        with open(files[0], "r") as f:
            data = json.load(f)

        if "name" not in data or "version" not in data:
            return False

        # Get the option values
        development = extravalues.get("NPM_INSTALL_DEV")
        registry = self._get_registry(extravalues, lines_before)

        # Initialize the npm environment
        d = bb.data.createCopy(tinfoil.config_data)
        d.setVar("S", srctree)
        d.setVar("NPM_REGISTRY", registry)
        d.setVar("NPM_CACHE_DIR", "${S}/.npm_cache")

        # Generate the shrinkwrap file
        shrinkwrap = self._generate_shrinkwrap(d, lines_before,
                                               extravalues, development)

        extravalues["PN"] = self._name_from_npm(data["name"])
        extravalues["PV"] = data["version"]

        if "description" in data:
            extravalues["SUMMARY"] = data["description"]

        if "homepage" in data:
            extravalues["HOMEPAGE"] = data["homepage"]

        classes.append("npm")
        handled.append("buildsystem")

        return True

def register_recipe_handlers(handlers):
    """
        Register the npm handler
    """
    handlers.append((NpmRecipeHandler(), 60))
