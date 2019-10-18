DEPENDS_prepend = "angular-cli-native "

ANGULAR_OUTPUT_PATH ?= "/var/www"

NG_BUILD_EXTRA_ARGS ?= ""

NPM_INSTALL_DEV = "1"

inherit npm

angular_do_install() {
    cd $(find ${B} -maxdepth 5 -name angular.json | head -n1 | xargs dirname)

    local NG_BUILD_ARGS="${NG_BUILD_ARGS} --verbose=true"
    local NG_BUILD_ARGS="${NG_BUILD_ARGS} --configuration=production"
    local NG_BUILD_ARGS="${NG_BUILD_ARGS} --deleteOutputPath=true"
    local NG_BUILD_ARGS="${NG_BUILD_ARGS} --outputPath=${D}/${ANGULAR_OUTPUT_PATH}"

    ng build ${NG_BUILD_EXTRA_ARGS} ${NG_BUILD_ARGS}
}

FILES_${PN} = " \
    ${ANGULAR_OUTPUT_PATH} \
"
EXPORT_FUNCTIONS do_install
