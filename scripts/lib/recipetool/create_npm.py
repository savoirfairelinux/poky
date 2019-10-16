# Copyright (C) 2016 Intel Corporation
# Copyright (C) 2019 Savoir-Faire Linux
#
# SPDX-License-Identifier: GPL-2.0-only
#
"""
    Recipe creation tool - npm module support plugin
"""

import json
import logging
import os
import re
import shutil
import sys
import tempfile
import bb
from bb.fetch2 import runfetchcmd
from recipetool.create import RecipeHandler

logger = logging.getLogger('recipetool')

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
            logger.error("Nothing provides 'nodejs-native' which is required for the build")
            logger.info("You will likely need to add a layer that provides nodejs")
            sys.exit(14)

        bindir = rd.getVar('STAGING_BINDIR_NATIVE')
        npmpath = os.path.join(bindir, 'npm')
        if not os.path.exists(npmpath):
            tinfoil.build_targets('nodejs-native', 'addto_recipe_sysroot')
            if not os.path.exists(npmpath):
                logger.error("Failed to add 'npm' to sysroot")
                sys.exit(14)

        d.prependVar("PATH", "{}:".format(bindir))

    @staticmethod
    def _run_npm_install(d, srctree, development, registry):
        """
            Run the 'npm install' command without building the sources (if any).
            This is only needed to generate the npm-shrinkwrap.json file.
        """

        cmd = "npm install"
        cmd += " --ignore-scripts"

        if development is None:
            cmd += " --production"

        if registry is not None:
            cmd += " --registry {}".format(registry)

        runfetchcmd(cmd, d, workdir=srctree)

    @staticmethod
    def _run_npm_shrinkwrap(d, srctree, development):
        """
            Run the 'npm shrinkwrap' command.
        """

        cmd = "npm shrinkwrap"

        if development is not None:
            cmd += " --development"

        runfetchcmd(cmd, d, workdir=srctree)

    def _generate_shrinkwrap(self, srctree, lines_before, lines_after, extravalues):
        """
            Check and generate the npm-shrinkwrap.json file if needed.
        """

        # Are we using the '--npm-dev' option ?
        development = extravalues.get("NPM_INSTALL_DEV")

        # Are we using the '--npm-registry' option ?
        registry_option = extravalues.get("NPM_REGISTRY")

        # Get the registry from the fetch url if using 'npm://registry.url'
        registry_fetch = None

        def varfunc(varname, origvalue, op, newlines):
            if varname == "SRC_URI":
                if origvalue.startswith("npm://"):
                    nonlocal registry_fetch
                    registry_fetch = origvalue.replace("npm://", "http://", 1).split(";")[0]
            return origvalue, None, 0, True

        bb.utils.edit_metadata(lines_before, ["SRC_URI"], varfunc)

        # Compute the proper registry value
        if registry_fetch is not None:
            registry = registry_fetch

            if registry_option is not None:
                logger.warning("The npm registry is specified multiple times")
                logger.info("Using registry from the fetch url: '{}'".format(registry))
                extravalues.pop("NPM_REGISTRY", None)

        elif registry_option is not None:
            registry = registry_option

        else:
            registry = None

        # Initialize the npm environment
        d = bb.data.createCopy(tinfoil.config_data)
        self._ensure_npm(d)

        # Check if a shinkwrap file is already in the source
        if os.path.exists(os.path.join(srctree, "npm-shrinkwrap.json")):
            logger.info("Using the npm-shrinkwrap.json provided in the sources")
            return

        # Generate the 'npm-shrinkwrap.json' file
        self._run_npm_install(d, srctree, development, registry)
        self._run_npm_shrinkwrap(d, srctree, development)

        # Save the shrinkwrap file in a temporary location
        tmpdir = tempfile.mkdtemp(prefix="recipetool-npm")
        tmpfile = os.path.join(tmpdir, "npm-shrinkwrap.json")
        shutil.move(os.path.join(srctree, "npm-shrinkwrap.json"), tmpfile)

        # Add the shrinkwrap file as 'extrafiles'
        extravalues.setdefault("extrafiles", {})
        extravalues["extrafiles"]["npm-shrinkwrap.json"] = tmpfile

        # Add a line in the recipe to handle the shrinkwrap file
        lines_after.append("NPM_SHRINKWRAP = \"${THISDIR}/${BPN}/npm-shrinkwrap.json\"")

        # Remove the 'node_modules' directory generated by 'npm install'
        bb.utils.remove(os.path.join(srctree, "node_modules"), recurse=True)

    @staticmethod
    def _recipe_name_from_npm(name):
        """
            Generate a recipe name based on the npm package name.
        """

        name = name.lower()
        name = re.sub("/", "-", name)
        name = re.sub("[^a-z\-]", "", name)
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

        with open(files[0], "r", errors="surrogateescape") as f:
            data = json.load(f)

        if "name" not in data or "version" not in data:
            return False

        self._generate_shrinkwrap(srctree, lines_before, lines_after, extravalues)

        extravalues["PN"] = self._recipe_name_from_npm(data["name"])
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
