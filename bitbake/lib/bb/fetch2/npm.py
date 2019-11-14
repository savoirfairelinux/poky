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

    @staticmethod
    def _is_semver(version):
        """
            Is the version string following the semver semantic?

            https://semver.org/spec/v2.0.0.html
        """
        regex = re.compile(
        r"""
        ^
        (0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)
        (?:-(
            (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
            (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
        ))?
        (?:\+(
            [0-9a-zA-Z-]+
            (?:\.[0-9a-zA-Z-]+)*
        ))?
        $
        """, re.VERBOSE)

        if regex.match(version) is None:
            return False

        return True

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

        if not self._is_semver(ud.version) and not ud.version == "latest":
            raise ParameterError("Parameter 'version' is invalid", ud.url)

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

    def need_update(self, ud, d):
        """
            Force a fetch, even if localpath exists?
        """
        if ud.version == "latest":
            return True

        if os.path.exists(ud.localpath):
            return False

        return True

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

        # Check if version is valid
        if ud.version == "latest":
            bb.warn("The npm package '{}' is using the latest version " \
                    "available. This could lead to non-reproducible " \
                    "builds.".format(ud.name))
        elif ud.version != view.get("version"):
            raise ParameterError("Parameter 'version' is invalid", ud.url)

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

def _parse_shrinkwrap(d, shrinkwrap_file=None):
    """
        Find and parse the shrinkwrap file to use.
    """

    def get_shrinkwrap_file(d):
        src_shrinkwrap = d.expand("${S}/npm-shrinkwrap.json")
        npm_shrinkwrap = d.getVar("NPM_SHRINKWRAP")

        if os.path.exists(src_shrinkwrap):
            bb.note("Using the npm-shrinkwrap.json provided in the sources")
            return src_shrinkwrap
        elif os.path.exists(npm_shrinkwrap):
            return npm_shrinkwrap

        bb.fatal("No mandatory NPM_SHRINKWRAP file found")

    if shrinkwrap_file is None:
        shrinkwrap_file = get_shrinkwrap_file(d)

    with open(shrinkwrap_file, "r") as f:
        shrinkwrap = json.load(f)

    return shrinkwrap

def foreach_dependencies(d, callback=None, shrinkwrap_file=None):
    """
        Run a callback for each dependencies of a shrinkwrap file.
        The callback is using the format:
            callback(name, version, deptree)
        with:
            name = the packet name (string)
            version = the packet version (string)
            deptree = the package dependency tree (array of strings)
    """
    shrinkwrap = _parse_shrinkwrap(d, shrinkwrap_file)

    def walk_deps(deps, deptree):
        out = []

        for name in deps:
            version = deps[name]["version"]
            subtree = [*deptree, name]
            out.extend(walk_deps(deps[name].get("dependencies", {}), subtree))
            if callback is not None:
                out.append(callback(name, version, subtree))

        return out

    return walk_deps(shrinkwrap.get("dependencies", {}), [])

def _get_url(d, name, version):
    registry = re.sub(r"https?://", "npm://", d.getVar("NPM_REGISTRY"))
    url = "{};name={};version={}".format(registry, name, version)
    return url

def fetch_dependency(d, name, version):
    """
        Fetch a dependency and return the tarball path.
    """
    url = _get_url(d, name, version)
    fetcher = bb.fetch2.Fetch([url], d)
    fetcher.download()
    return fetcher.localpath(url)

def fetch_dependencies(d, shrinkwrap_file=None):
    """
        Fetch all dependencies of a shrinkwrap file.
    """

    def handle_dependency(name, version, *unused):
        fetch_dependency(d, name, version)

    foreach_dependencies(d, handle_dependency, shrinkwrap_file)

def unpack_dependencies(d, shrinkwrap_file=None):
    """
        Unpack all dependencies of a shrinkwrap file. The dependencies are
        unpacked in the source tree and added to the npm cache.
    """
    bb.utils.remove(d.getVar("NPM_CACHE_DIR"), recurse=True)
    bb.utils.remove(d.expand("${S}/node_modules/"), recurse=True)

    def cache_dependency(tarball):
        cmd = "npm cache add '{}'".format(tarball)
        cmd += " --offline"
        cmd += " --proxy=http://invalid.org"
        cmd += d.expand(" --cache=${NPM_CACHE_DIR}")
        runfetchcmd(cmd, d)

    def unpack_dependency(tarball, srctree):
        cmd = "tar --extract --gzip --file='{}'".format(tarball)
        cmd += " --no-same-owner"
        cmd += " --transform 's:^package/::'"
        bb.utils.mkdirhier(srctree)
        runfetchcmd(cmd, d, workdir=srctree)

    def handle_dependency(name, version, deptree):
        url = _get_url(d, name, version)
        fetcher = bb.fetch2.Fetch([url], d)
        tarball = fetcher.localpath(url)
        cache_dependency(tarball)
        relpath = os.path.join(*[os.path.join("node_modules", d) for d in deptree])
        abspath = os.path.join(d.getVar("S"), relpath)
        unpack_dependency(tarball, abspath)

    foreach_dependencies(d, handle_dependency, shrinkwrap_file)
