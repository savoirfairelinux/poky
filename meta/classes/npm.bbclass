# Copyright (C) 2019 Savoir-Faire Linux
#
# This bbclass builds and installs an npm package to the target. The package
# sources files should be fetched in the calling recipe by using the SRC_URI
# variable. The ${S} variable should be updated depending of your fetcher.
#
# Usage:
#  SRC_URI = "..."
#  inherit npm
#
# Optional variables:
#  NPM_SHRINKWRAP:
#       Provide a shrinkwrap file [1]. If available a shrinkwrap file in the
#       sources has priority over the one provided. A shrinkwrap file is
#       mandatory in order to ensure build reproducibility.
#       1: https://docs.npmjs.com/files/shrinkwrap.json
#
#  NPM_INSTALL_DEV:
#       Set to 1 to also install devDependencies.
#
#  NPM_REGISTRY:
#       Use the specified registry.
#
#  NPM_ARCH:
#       Override the auto generated npm architecture.
#
#  NPM_INSTALL_EXTRA_ARGS:
#       Add extra arguments to the 'npm install' execution.
#       Use it at your own risk.

DEPENDS_prepend = "nodejs-native "
RDEPENDS_${PN}_prepend = "nodejs "

NPM_SHRINKWRAP ?= "${THISDIR}/${BPN}/npm-shrinkwrap.json"

NPM_INSTALL_DEV ?= "0"

NPM_REGISTRY ?= "https://registry.npmjs.org"

# function maps arch names to npm arch names
def npm_oe_arch_map(target_arch):
    import re
    if   re.match('p(pc|owerpc)(|64)', target_arch): return 'ppc'
    elif re.match('i.86$', target_arch): return 'ia32'
    elif re.match('x86_64$', target_arch): return 'x64'
    elif re.match('arm64$', target_arch): return 'arm'
    return target_arch

NPM_ARCH ?= "${@npm_oe_arch_map(d.getVar('TARGET_ARCH'))}"

NPM_INSTALL_EXTRA_ARGS ?= ""

B = "${WORKDIR}/build"

npm_install_shrinkwrap() {
    # This function ensures that there is a shrinkwrap file in the specified
    # directory. A shrinkwrap file is mandatory to have reproducible builds.
    # If the shrinkwrap file is not already included in the sources,
    # the recipe can provide one by using the NPM_SHRINKWRAP option.
    # This function returns the filename of the installed file (if any).
    if [ -f ${1}/npm-shrinkwrap.json ]
    then
        bbnote "Using the npm-shrinkwrap.json provided in the sources"
    elif [ -f ${NPM_SHRINKWRAP} ]
    then
        install -m 644 ${NPM_SHRINKWRAP} ${1}
        echo ${1}/npm-shrinkwrap.json
    else
        bbfatal "No mandatory NPM_SHRINKWRAP file found"
    fi
}

npm_do_compile() {
    # This function executes the 'npm install' command which builds and
    # installs every dependencies needed for the package. All the files are
    # installed in a build directory ${B} without filtering anything. To do so,
    # a combination of 'npm pack' and 'npm install' is used to ensure that the
    # files in ${B} are actual copies instead of symbolic links (which is the
    # default npm behavior).

    # The npm command use by default a cache which is located in '~/.npm'. In
    # order to force the next npm commands to disable caching, the npm cache
    # needs to be cleared. But not to alter the local cache, the npm config
    # needs to be updated to use another cache directory. The HOME needs to be
    # updated as well to avoid modifying the local '~/.npmrc' file.
    HOME=${WORKDIR}
    npm config set cache ${WORKDIR}/npm_cache
    npm cache clear --force

    # First ensure that there is a shrinkwrap file in the sources.
    local NPM_SHRINKWRAP_INSTALLED=$(npm_install_shrinkwrap ${S})

    # Then create a tarball from a npm package whose sources must be in ${S}.
    local NPM_PACK_FILE=$(cd ${WORKDIR} && npm pack ${S}/)

    # Finally install and build the tarball package in ${B}.
    local NPM_INSTALL_ARGS="${NPM_INSTALL_ARGS} --loglevel silly"
    local NPM_INSTALL_ARGS="${NPM_INSTALL_ARGS} --prefix=${B}"
    local NPM_INSTALL_ARGS="${NPM_INSTALL_ARGS} --global"

    if [ "${NPM_INSTALL_DEV}" != 1 ]
    then
        local NPM_INSTALL_ARGS="${NPM_INSTALL_ARGS} --production"
    fi

    local NPM_INSTALL_GYP_ARGS="${NPM_INSTALL_GYP_ARGS} --arch=${NPM_ARCH}"
    local NPM_INSTALL_GYP_ARGS="${NPM_INSTALL_GYP_ARGS} --target_arch=${NPM_ARCH}"
    local NPM_INSTALL_GYP_ARGS="${NPM_INSTALL_GYP_ARGS} --release"

    cd ${WORKDIR} && npm install \
        ${NPM_INSTALL_EXTRA_ARGS} \
        ${NPM_INSTALL_GYP_ARGS} \
        ${NPM_INSTALL_ARGS} \
        ${NPM_PACK_FILE}

    # Clean source tree.
    rm -f ${NPM_SHRINKWRAP_INSTALLED}
}

npm_do_install() {
    # This function creates the destination directory from the pre installed
    # files in the ${B} directory.

    # Copy the entire lib and bin directories from ${B} to ${D}.
    install -d ${D}/${libdir}
    cp --no-preserve=ownership --recursive ${B}/lib/. ${D}/${libdir}

    if [ -d "${B}/bin" ]
    then
        install -d ${D}/${bindir}
        cp --no-preserve=ownership --recursive ${B}/bin/. ${D}/${bindir}
    fi

    # If the package (or its dependencies) uses node-gyp to build native addons,
    # object files, static libraries or other temporary files can be hidden in
    # the lib directory. To reduce the package size and to avoid QA issues
    # (staticdev with static library files) these files must be removed.

    # Remove any node-gyp directory in ${D} to remove temporary build files.
    for GYP_D_FILE in $(find ${D} -regex ".*/build/Release/[^/]*.node")
    do
        local GYP_D_DIR=${GYP_D_FILE%/Release/*}

        rm --recursive --force ${GYP_D_DIR}
    done

    # Copy only the node-gyp release files from ${B} to ${D}.
    for GYP_B_FILE in $(find ${B} -regex ".*/build/Release/[^/]*.node")
    do
        local GYP_D_FILE=${D}/${prefix}/${GYP_B_FILE#${B}}

        install -d ${GYP_D_FILE%/*}
        install -m 755 ${GYP_B_FILE} ${GYP_D_FILE}
    done

    # Remove the shrinkwrap file which does not need to be packed.
    rm -f ${D}/${libdir}/node_modules/*/npm-shrinkwrap.json
    rm -f ${D}/${libdir}/node_modules/@*/*/npm-shrinkwrap.json

    # node(1) is using /usr/lib/node as default include directory and npm(1) is
    # using /usr/lib/node_modules as install directory. Let's make both happy.
    ln -fs node_modules ${D}/${libdir}/node
}

FILES_${PN} += " \
    ${bindir} \
    ${libdir} \
"

EXPORT_FUNCTIONS do_compile do_install
