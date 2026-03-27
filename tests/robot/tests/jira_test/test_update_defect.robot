*** Settings ***
Library             ../../resources/APIKeywords.py
Library             Collections
Resource            ../../resources/service_setup.robot
Resource            ../../resources/variables.resource
Resource            ../../resources/Comparators.resource

Suite Setup         Setup Test Suite
Suite Teardown      Teardown Test Suite


*** Test Cases ***
Put Project Update Defect Update Title
    ${title}=    Set Variable    add Title
    Assert Value Not Present In Defect    title    ${title}

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"title":"${title}","status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert Value Present In Defect    title    ${title}

Put Project Update Defect Update Description
    ${description}=    Set Variable    add description
    Assert Value Not Present In Defect    description    ${description}

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"description":"${description}","status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert Value Present In Defect    description    ${description}

Put Project Update Defect Update Status
    ${status}=    Set Variable    In Arbeit
    Assert Value Not Present In Defect    status    ${status}

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"status": "${status}", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert Value Present In Defect    status    ${status}

Put Project Update Defect Update Classification
    ${classification}=    Set Variable    Task
    Assert Value Not Present In Defect    classification    ${classification}

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"status": "", "classification": "${classification}", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert Value Present In Defect    classification    ${classification}

Put Project Update Defect Update Userdefiend Value Text
    ${user_defined_fields}=    Set Variable    [{"name":"Text","value":"Hello world"}]

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "userDefinedFields": ${user_defined_fields}, "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert In User Defeind Values    ${user_defined_fields}

Put Project Update Defect Update Userdefiend Value Dropdown
    ${user_defined_fields}=    Set Variable    [{"name":"dropdown","value":"Option 1"}]

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "userDefinedFields": ${user_defined_fields}, "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert In User Defeind Values    ${user_defined_fields}

Put Project Update Defect Update Userdefiend Value Label
    ${user_defined_fields}=    Set Variable    [{"name":"label","value":"Label_1"}]

    ${response}=    Put Project Defect Update
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "userDefinedFields": ${user_defined_fields}, "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

    Assert In User Defeind Values    ${user_defined_fields}


*** Keywords ***
Setup Test Suite
    Start Defect Service    JiraDefectClient    jira.toml
    ${response}=    Post Project Defect Create
    ...    project=Jira Scrum (JS)
    ...    body={"defect": {"status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ${json}=    Set Variable    ${response.json()}
    ${name_value}=    Get From Dictionary    ${json}    value
    Set Suite Variable    ${defect_id}    ${name_value}

Teardown Test Suite
    ${response}=    Post Project Defect Delete
    ...    project=Jira Scrum (JS)
    ...    defect_id=${defect_id}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    Stop Defect Service
