*** Settings ***
Library     ../../resources/APIKeywords.py
Resource    ../../resources/variables.resource
Library     Collections


*** Variables ***
${defect_name}      None


*** Test Cases ***
Get Check In Credentials No Project Return bool
    ${response}=    Get Check Login
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, bool)

Get Check In Credentials With Project Return bool
    ${response}=    Get Check Login
    ...    project=${project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, bool)

Get Settings Return Return 200 With Valid Structure
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
    Should Be Equal    ${name_value}    Jira

Get Projects Rteurn Return 200 With List Of Project Names
    ${response}=    Get Projects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, list)
    Should Not Be Empty    ${json}

Get Project Control Fields Return 200 With Dictionary
    ${response}=    Get Project Control Fields
    ...    project=${project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    Priorität
    Dictionary Should Contain Key    ${json}    status
    Dictionary Should Not Contain Key    ${json}    Hello World

Get Project Control Fields Return 404 With Dictionary
    ${response}=    Get Project Control Fields
    ...    project=${not_a_project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 404

Get Project Defects Return 200 With Protocolled Defect Set With Success
    ${response}=    Get Project Defects
    ...    project=${project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    Should Be True    isinstance(${json["value"]}, list)
    Should Be True    isinstance(${json["protocol"]}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}

Get Project Defects Return 200 With Protocolled Defect Set With Warnings
    ${response}=    Get Project Defects
    ...    project=${not_a_project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    Should Be True    isinstance(${json["value"]}, list)
    Should Be True    isinstance(${json["protocol"]}, dict)
    Should Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["generalErrors"]}

Get Project Extended Defect Return 200 With Defect With Attributes
    ${response}=    Get Project Extended Defects
    ...    project=${project}
    ...    defect_id=JS-4
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, dict)
    Dictionary Should Contain Key    ${json}    status
    Dictionary Should Contain Key    ${json}    id
    Dictionary Should Contain Key    ${json}    attributes
    ${attributes}=    Set Variable    ${json["attributes"]}
    Dictionary Should Contain Key    ${json}    title
    Dictionary Should Contain Key    ${json}    status

Get Project Extended Defect Return404 Project Not Found
    ${response}=    Get Project Extended Defects
    ...    project=${not_a_project}
    ...    defect_id=JS-4
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 404

Get Project Extended Defect Return 404 Defect Not Found
    ${response}=    Get Project Extended Defects
    ...    project=${project}
    ...    defect_id=JeeS-4
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 404

Get Project Extended Defect Return 404 Project and Defect Not Found
    ${response}=    Get Project Extended Defects
    ...    project=${not_a_project}
    ...    defect_id=JeeS-4
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 404

Get Projekct UDFs Return 200 List of User Defiend Attributes
    ${response}=    Get Project Udfs
    ...    project=${project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Should Be True    isinstance(${json}, list)
    Should Not Be Empty    ${json}

Get Projekct UDFs Return 404
    ${response}=    Get Project Udfs
    ...    project=${not_a_project}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 404

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
    Should Not Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["successes"]}
    Set Suite Variable    ${defect_name}    ${name_value}

Post Project Create Defect Return 200 With Error Invaild Project In Protocolled String
    ${response}=    Post Project Defect Create
    ...    project=${not_a_project}
    ...    body={"defect":{"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
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
    Should Start With    ${json["protocol"]["generalErrors"][0]["message"]}    Unknown project

Put Project Update Defect Return 200 With Protocol
    ${response}=    Put Project Defect Update
    ...    project=${project}
    ...    defect_id=${defect_name}
    ...    body={"defect": {"title":"add Title","status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

Put Project Update Defect Return 200 With General Errors in Protocol
    ${response}=    Put Project Defect Update
    ...    project=${not_a_project}
    ...    defect_id=${defect_name}
    ...    body={"defect": {"title":"add Title","status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["generalErrors"]}

Post Project Defect Batch Return 200 With Potocolled Defect Set
    ${response}=    Post Project Defect Batch
    ...    project=${project}
    ...    body={"defectIds": ["${defect_name}"],"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    Should Be True    isinstance(${json}, dict)
    Should Not Be Empty    ${json["value"]}
    Should Be True    len(${json["value"]}) == 1
    Should Not Be Empty    ${json["protocol"]["successes"]}

Post Project Defect Batch Return 200 With Invaild Project Potocolled Defect Set
    ${response}=    Post Project Defect Batch
    ...    project=${not_a_project}
    ...    body={"defectIds": ["${defect_name}"],"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    Should Be True    isinstance(${json}, dict)
    Should Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["generalErrors"]}
    Should Start With    ${json["protocol"]["generalErrors"][0]["message"]}    Unknown project

Post Project Defect Batch Return 200 With Invaild Id Potocolled Defect Set
    ${response}=    Post Project Defect Batch
    ...    project=${project}
    ...    body={"defectIds": ["No ID"],"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    value
    Dictionary Should Contain Key    ${json}    protocol
    Should Be True    isinstance(${json}, dict)
    Should Be Empty    ${json["value"]}
    Should Not Be Empty    ${json["protocol"]["warnings"]}

Post Project Delete Defects Return 200 With Protocol
    ${response}=    Post Project Defect Delete
    ...    project=${project}
    ...    defect_id=${defect_name}
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["successes"]}

Post Project Delete Defects Return 200 With General Warnings In Protocol
    ${response}=    Post Project Defect Delete
    ...    project=${project}
    ...    defect_id=NO ID
    ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 200
    ${json}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${json}    successes
    Dictionary Should Contain Key    ${json}    warnings
    Dictionary Should Contain Key    ${json}    errors
    Dictionary Should Contain Key    ${json}    generalWarnings
    Dictionary Should Contain Key    ${json}    generalErrors
    Should Not Be Empty    ${json["generalErrors"]}

Post Project Delete Defects Return 200 With General Errors Protocol
    ${response}=    Post Project Defect Delete
    ...    project=${not_a_project}
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
    Should Not Be Empty    ${json["generalErrors"]}
