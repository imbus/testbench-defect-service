*** Settings ***
Library     ../../resources/APIKeywords.py
Resource    ../../resources/variables.resource
Library     Collections


*** Test Cases ***
Check Project Control Fields Differe
    ${response}=    Get Project Control Fields
    ...    project=${project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    Priorität
    Dictionary Should Not Contain Key    ${json}    Status

    ${response}=    Get Project Control Fields
    ...    project=Testproject 2 (T2)
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Not Contain Key    ${json}    Priorität
    Dictionary Should Contain Key    ${json}    Status
