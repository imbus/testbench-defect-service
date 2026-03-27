*** Settings ***
Library     ../../resources/APIKeywords.py
Resource    ../../resources/variables.resource
Library     Collections


*** Test Cases ***
Post Project Create Defect Return 200 With Protocolled String
    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["errors"]}
    Should Be Equal    ${json["protocol"]["errors"]["${project}"][0]["message"]}
    ...    Cannot create issue because the Jira project '${project}' has been configured as read-only

Put Project Update Defect Return 200 With Protocol
    ${response}=    Put Project Defect Update
    ...    project=${project}
    ...    defect_id=SomeID
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["errors"]}
    Should Be Equal
    ...    ${json["errors"]["${project}"][0]["message"]}
    ...    Cannot update issue because the Jira project '${project}' has been configured as read-only

Post Project Delete Defects Return 200 With Protocol
    ${response}=    Post Project Defect Delete
    ...    project=${project}
    ...    defect_id=SomeID
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["errors"]}
    Should Be Equal    ${json["errors"]["${project}"][0]["message"]}
    ...    Cannot delete the issue because the Jira project '${project}' has been configured as read-only
