# Copyright (C) 2019 Savoir-Faire Linux
#
# SPDX-License-Identifier: GPL-2.0-only
#
"""
BitBake 'Fetch' npm implementation

npm fetcher support the SRC_URI with format of:
SRC_URI = "npm://some.registry.url;OptionA=xxx;OptionB=xxx;..."

Supported SRC_URI options are:

- name
   The npm package name. This is a mandatory parameter.

- version
    The npm package version. This is a mandatory parameter.

- downloadfilename
    Specifies the filename used when storing the downloaded file.

"""

import base64
import json
import os
import re
import bb
from bb.fetch2 import ChecksumError
from bb.fetch2 import FetchError
from bb.fetch2 import MissingParameterError
from bb.fetch2 import ParameterError
from bb.fetch2 import FetchMethod
from bb.fetch2 import URI
from bb.fetch2 import check_network_access
from bb.fetch2 import runfetchcmd

class Npm(FetchMethod):
    """
        Class to fetch a package from a npm registry
    """

    def supports(self, ud, d):
        """
            Check if a given url can be fetched with npm
        """
        return ud.type in ['npm']

    def urldata_init(self, ud, d):
        """
            Init npm specific variables within url data
        """

        # Get the 'name' parameter
        if "name" in ud.parm:
            ud.name = ud.parm.get("name")

        if not ud.name:
            raise MissingParameterError("Parameter 'name' required", ud.url)

        # Get the 'version' parameter
        if "version" in ud.parm:
            ud.version = ud.parm.get("version")

        if not ud.version:
            raise MissingParameterError("Parameter 'version' required", ud.url)

        # Get the 'registry' part of the url
        registry = re.sub(r"^npm://", "", ud.url.split(";")[0])
        ud.registry = "http://" + registry

        # Update the NPM_REGISTRY in the environment
        d.setVar("NPM_REGISTRY", ud.registry)

        # Using the 'downloadfilename' parameter as local filename or the
        # npm package name.
        if "downloadfilename" in ud.parm:
            ud.basename = ud.parm["downloadfilename"]
        else:
            # Scoped package names (with the @) use the same naming convention
            # as the 'npm pack' command.
            if ud.name.startswith("@"):
                ud.basename = re.sub("/", "-", ud.name[1:])
            else:
                ud.basename = ud.name
            ud.basename += "-" + ud.version + ".tgz"

        ud.localfile = os.path.join("npm", registry, d.expand(ud.basename))

        ud.basecmd = d.getVar("FETCHCMD_wget")

        if not ud.basecmd:
            ud.basecmd = "wget"
            ud.basecmd += " --tries=2"
            ud.basecmd += " --timeout=30"
            ud.basecmd += " --passive-ftp"
            ud.basecmd += " --no-check-certificate"

    @staticmethod
    def _run_npm_view(ud, d):
        """
            Run the 'npm view' command to get informations about a npm package.
        """
        cmd = "npm view '{}@{}'".format(ud.name, ud.version)
        cmd += " --json"
        cmd += " --registry={}".format(ud.registry)
        check_network_access(d, cmd, ud.registry)
        view_string = runfetchcmd(cmd, d)

        if not view_string:
            raise ParameterError("Invalid view from npm", ud.url)

        view = json.loads(view_string)

        if view.get("error") is not None:
            raise ParameterError(view.get("error", {}).get("summary"), ud.url)

        if isinstance(view, list):
            return view[-1]

        return view

    @staticmethod
    def _run_wget(ud, d, cmd):
        """
            Run the 'wget' command
        """
        check_network_access(d, cmd, ud.url)
        runfetchcmd(cmd, d)

    @staticmethod
    def _check_integrity(integrity, filename):
        """
            Check the subresource integrity.

            https://w3c.github.io/webappsec-subresource-integrity
            https://www.w3.org/TR/CSP2/#source-list-syntax
        """
        algo, value_b64 = integrity.split("-", maxsplit=1)
        value_hex = base64.b64decode(value_b64).hex()

        if algo == "sha256":
            return value_hex == bb.utils.sha256_file(filename)
        elif algo == "sha384":
            return value_hex == bb.utils.sha384_file(filename)
        elif algo == "sha512":
            return value_hex == bb.utils.sha512_file(filename)

        return False

    def download(self, ud, d):
        """
            Fetch url
        """
        view = self._run_npm_view(ud, d)

        uri = URI(view.get("dist", {}).get("tarball"))
        integrity = view.get("dist", {}).get("integrity")
        shasum = view.get("dist", {}).get("shasum")

        cmd = ud.basecmd

        bb.utils.mkdirhier(os.path.dirname(ud.localpath))
        cmd += " --output-document='{}'".format(ud.localpath)

        if os.path.exists(ud.localpath):
            cmd += " --continue"

        cmd += d.expand(" --directory-prefix=${DL_DIR}")
        cmd += " '{}'".format(uri)

        self._run_wget(ud, d, cmd)

        if not os.path.exists(ud.localpath):
            raise FetchError("The fetched file does not exist")

        if os.path.getsize(ud.localpath) == 0:
            os.remove(ud.localpath)
            raise FetchError("The fetched file is empty")

        if integrity is not None:
            if not self._check_integrity(integrity, ud.localpath):
                raise ChecksumError("The fetched file integrity mismatch")
        elif shasum is not None:
            if shasum != bb.utils.sha1_file(ud.localpath):
                raise ChecksumError("The fetched file shasum mismatch")

    def unpack(self, ud, rootdir, d):
        """
            Unpack the downloaded archive to rootdir
        """
        cmd = "tar --extract --gzip --file='{}'".format(ud.localpath)
        cmd += " --no-same-owner"
        cmd += " --transform 's:^package/:npm/:'"
        runfetchcmd(cmd, d, workdir=rootdir)
