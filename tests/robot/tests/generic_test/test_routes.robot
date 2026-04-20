*** Settings ***
Library     ../../resources/APIKeywords.py
Library     Collections
Resource    ../../resources/variables.resource


*** Variables ***
${defect_name}      None


*** Test Cases ***
Get Settings Should Return 200 With Valid Structure
    ${response}=    Get Settings
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    name
    Dictionary Should Contain Key    ${json}    description
    Dictionary Should Contain Key    ${json}    readonly
    ${name_value}=    Get From Dictionary    ${json}    name
    ${description_value}=    Get From Dictionary    ${json}    description
    ${readonly_value}=    Get From Dictionary    ${json}    readonly
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance($description_value, str)
    Should Be True    isinstance($readonly_value, bool)

Get Check Login Should Return True With Valid Credentials
    ${response}=    Get Check Login
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, bool)
    Should Be True    ${json}

Get Projects Should Return List Of Project Names
    ${response}=    Get Projects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, list)
    Should Not Be Empty    ${json}

Get Project Control Fields Should Return Dictionary
    ${response}=    Get Project Control Fields
    ...    project=defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    status
    Dictionary Should Contain Key    ${json}    priority

Get Project Defects Should Return Protocolled Defect Set
    ${response}=    Get Project Defects
    ...    project=defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    Should Be True    isinstance(${json['value']}, list)
    Should Be True    isinstance(${json['protocol']}, dict)

Get Project UDFs Should Return List Of User Defined Fields
    ${response}=    Get Project Udfs
    ...    project=defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, list)

Get Supports Changes Timestamps Should Return Boolean
    ${response}=    Get Supports Changes Timestamps
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, bool)

Post Batch Project Defects Should Return Defect List
    ${response}=    Post Project Defect Batch
    ...    project=defects
    ...    body={"defectIds":["BUG-4", "BUG-5"],"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance(${value}, list)
    Should Be True    isinstance(${json['protocol']}, dict)

Post Project Create Should Return Protocolled String
    ${response}=    Post Project Defect Create
    ...    project=defects
    ...    body={"defect":{"status": "ready", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z","principal": {"username": "arivera_dev", "password": "hashed_password_example_123"}},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Set Suite Variable    ${defect_name}    ${name_value}

Put Project Update Defect Should Return Protocol
    ${response}=    Put Project Defect Update
    ...    project=defects
    ...    defect_id=${defect_name}
    ...    body={"defect":{"status": "ready", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z","principal": {"username": "arivera_dev", "password": "hashed_password_example_123"}}, "syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Be True    isinstance(${json}, dict)

Post Prject Delete Defect Should Return Protocol
    ${response}=    Post Project Defect Delete
    ...    project=defects
    ...    defect_id=${defect_name}
    ...    body={"defect":{"status": "ready", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z","principal": {"username": "arivera_dev", "password": "hashed_password_example_123"}},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Be True    isinstance(${json}, dict)

Get Project Extended Defect Should Return Defect With Attributes
    ${response}=    Get Project Extended Defects
    ...    project=defects
    ...    defect_id=BUG-5
    ...    body=${syncContext}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    id
    Dictionary Should Contain Key    ${json}    attributes
    Dictionary Should Contain Key    ${json}    principal
    Dictionary Should Contain Key    ${json}    status
    Dictionary Should Contain Key    ${json}    classification
    Should Be True    isinstance(${json}, dict)
