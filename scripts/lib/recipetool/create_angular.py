# Copyright (C) 2016 Intel Corporation
#
# SPDX-License-Identifier: GPL-2.0-only
#
"""
    Recipe creation tool - angular module support plugin
"""

import logging
import os
import sys
import bb
from recipetool.create import RecipeHandler

logger = logging.getLogger("recipetool")

tinfoil = None

def tinfoil_init(instance):
    """
        Initialize tinfoil.
    """

    global tinfoil
    tinfoil = instance

class AngularPreRecipeHandler(RecipeHandler):
    """
        Class to handle the angular recipe creation
    """

    def process(self, srctree, classes, lines_before, lines_after, handled, extravalues):
        """
            Handle the angular recipe creation
        """

        if "buildsystem" in handled:
            return False

        files = RecipeHandler.checkfiles(srctree, ["angular.json"])

        if not files:
            return False

        extravalues["NPM_INSTALL_DEV"] = 1

        return True

class AngularPostRecipeHandler(RecipeHandler):
    """
        Class to handle the angular recipe creation
    """

    @staticmethod
    def _check_angular(d):
        """
            Check if the 'ng' command is available in the recipes, then build it.
        """

        if not tinfoil.recipes_parsed:
            tinfoil.parse_recipes()

        try:
            ngd = tinfoil.parse_recipe("angular-cli-native")
        except bb.providers.NoProvider:
            logger.error("Nothing provides 'angular-cli-native' which is required for the build")
            logger.info("You will likely need to add a layer that provides angular-cli")
            sys.exit(14)

        bindir = ngd.getVar("STAGING_BINDIR_NATIVE")
        ng = os.path.join(bindir, "ng")

        if not os.path.exists(ng):
            tinfoil.build_targets("angular-cli-native", "addto_recipe_sysroot")

            if not os.path.exists(ng):
                logger.error("Failed to add 'ng' to sysroot")
                sys.exit(14)

    def process(self, srctree, classes, lines_before, lines_after, handled, extravalues):
        """
            Handle the angular recipe creation
        """

        if "buildsystem" not in handled or "npm" not in classes:
            return False

        files = RecipeHandler.checkfiles(srctree, ["angular.json"])

        if not files:
            return False

        d = bb.data.createCopy(tinfoil.config_data)
        self._check_angular(d)

        classes.remove("npm")
        classes.append("angular")

        extravalues.pop("NPM_INSTALL_DEV", None)

        return True

def register_recipe_handlers(handlers):
    """
        Register the angular handler
    """

    handlers.append((AngularPreRecipeHandler(), 65))
    handlers.append((AngularPostRecipeHandler(), 55))
