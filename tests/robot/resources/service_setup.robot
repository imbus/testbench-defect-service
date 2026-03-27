*** Settings ***
Library     Process
Library     Collections


*** Variables ***
${service_process}      None


*** Keywords ***
Stop Defect Service
    ${is_running}=    Is Process Running    ${service_process}
    IF    ${is_running}
        ${pid}=    Get Process Id    ${service_process}
        Log    Attempting to kill PID: ${pid}
        Run Process    taskkill    /F    /T    /PID    ${pid}

        ${result}=    Wait For Process    ${service_process}    timeout=5s
        Log    Service process output: ${result.stdout}
        Log    Service process error: ${result.stderr}
    END

Start Defect Service
    [Arguments]    ${reader_class}=${EMPTY}    ${reader_config}=${EMPTY}
    ${command}=    Create List    testbench-defect-service    start
    IF    "${reader_class}"
        Append To List    ${command}    --client-class    ${reader_class}
    END

    IF    "${reader_config}"
        Append To List    ${command}    --client-config    ${reader_config}
    END

    ${process}=    Start Process
    ...    @{command}
    ...    stdout=${TEMPDIR}/service_stdout.txt
    ...    stderr=${TEMPDIR}/service_stderr.txt
    ...    alias=defect_service
    Set Suite Variable    ${service_process}    ${process}
    Sleep    2s    # Give service time to start
    ${is_running}=    Is Process Running    ${service_process}
    IF    ${is_running} == False
        Terminate Process    ${service_process}    kill=True
        ${result}=    Get Process Result    ${service_process}
        Log    Service process output: ${result.stdout}    ERROR
        Log    Service process error: ${result.stderr}    ERROR
        Fail    Service process crashed during startup with return code ${result.rc}
    END
