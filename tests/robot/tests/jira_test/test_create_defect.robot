*** Settings ***
Library             ../../resources/APIKeywords.py
Library             Collections
Resource            ../../resources/variables.resource
Resource            ../../resources/Comparators.resource
Resource            ../../resources/Teardown.robot

Test Teardown       Cleanup Defect After Test    ${project}    ${defect_id}


*** Test Cases ***
Post Project Create Defect With Title
    ${title}=    Set Variable    Title

    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"title":"${title}", "status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Set Suite Variable    ${defect_id}    ${name_value}
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}

    Assert Value Present In Defect    title    ${title}

Post Project Create Defect With Description
    ${description}=    Set Variable    description

    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"description": "${description}", "status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Set Suite Variable    ${defect_id}    ${name_value}
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}

    Assert Value Present In Defect    description    ${description}

Post Project Create Defect With Reporter
    ${reporter}=    Set Variable    Bastian Wagner

    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"reporter": "${reporter}", "status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_id}    ${name_value}

    Assert Value Present In Defect    reporter    ${reporter}

Post Project Create Defect With Invaild Reporter
    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"reporter": "Max Musterman", "status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Should Not Be Empty    ${json["protocol"]["generalWarnings"]}
    Set Suite Variable    ${defect_id}    ${name_value}

Post Project Create Defect With Invalid Transition
    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "Ready", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_id}    ${name_value}

Post Project Create Defect With Empty Transition
    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_id}    ${name_value}

Post Project Create Defect With Invalid Classification
    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bugs", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["generalErrors"]}
    Set Suite Variable    ${defect_id}    ${name_value}

Post Project Create Defect With Invalid Priority
    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "Highestes", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["generalErrors"]}
    Set Suite Variable    ${defect_id}    ${name_value}

Post Project Create Defect With Userdefiend Value Text
    ${user_defined_fields}=    Set Variable    [{"name":"Text","value":"Hello world"}]

    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z","userDefinedFields": ${user_defined_fields}, "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_id}    ${name_value}

    Assert In User Defeind Values    ${user_defined_fields}

Post Project Create Defect With Userdefiend Value Dropdown
    ${user_defined_fields}=    Set Variable    [{"name":"dropdown","value":"Option 1"}]

    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z","userDefinedFields": ${user_defined_fields}, "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_id}    ${name_value}

    Assert In User Defeind Values    ${user_defined_fields}

Post Project Create Defect With Userdefiend Value Label
    ${user_defined_fields}=    Set Variable    [{"name":"label","value":"Label_1"}]

    ${response}=    Post Project Defect Create
    ...    project=${project}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z","userDefinedFields": ${user_defined_fields}, "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    ${name_value}=    Get From Dictionary    ${json}    value
    Should Be True    isinstance($name_value, str)
    Should Be True    isinstance(${json['protocol']}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_id}    ${name_value}

    Assert In User Defeind Values    ${user_defined_fields}
