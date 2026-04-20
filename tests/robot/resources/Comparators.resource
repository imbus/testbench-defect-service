*** Settings ***
Library     APIKeywords.py
Resource    variables.resource
Library     Collections


*** Keywords ***
Assert Value Not Present In Defect
    [Arguments]    ${field}    ${excpected}
    ${response_batch}=    Post Project Defect Batch
    ...    project=Jira Scrum (JS)
    ...    body={"defectIds": ["${defect_id}"],"syncContext": ${syncContext}}
    ${defect}=    Set Variable    ${response_batch.json()}
    Should Not Be Equal    ${defect["value"][0]["${field}"]}    ${excpected}

Assert Value Present In Defect
    [Arguments]    ${field}    ${excpected}
    ${response_batch}=    Post Project Defect Batch
    ...    project=Jira Scrum (JS)
    ...    body={"defectIds": ["${defect_id}"],"syncContext": ${syncContext}}
    ${defect}=    Set Variable    ${response_batch.json()}
    Should Be Equal    ${defect["value"][0]["${field}"]}    ${excpected}

Assert In User Defeind Values
    [Arguments]    ${excpected}
    ${response_batch}=    Post Project Defect Batch
    ...    project=Jira Scrum (JS)
    ...    body={"defectIds": ["${defect_id}"],"syncContext": ${syncContext}}
    ${defect}=    Set Variable    ${response_batch.json()}
    ${user_fields}=    Evaluate
    ...    [{"name": field["name"], "value": field["value"]} for field in ${defect["value"][0]["userDefinedFields"]}]
    ${expected_list}=    Evaluate    json.loads('${excpected}')    json

    FOR    ${expected_item}    IN    @{expected_list}
        ${found}=    Set Variable    ${False}
        FOR    ${user_field}    IN    @{user_fields}
            ${name_match}=    Evaluate    "${user_field['name']}" == "${expected_item['name']}"
            IF    not ${name_match}    CONTINUE
            ${value_match}=    Evaluate    "${expected_item['value']}" in str("""${user_field['value']}""")
            IF    ${value_match}
                ${found}=    Set Variable    ${True}
                BREAK
            END
        END
        Should Be True    ${found}    Expected item ${expected_item} not found in user defined fields
    END
