*** Settings ***
Library     APIKeywords.py
Resource    variables.resource


*** Keywords ***
Cleanup Defect After Test
    [Arguments]    ${project}    ${defect_id}
    IF    $defect_id != ""
        Post Project Defect Delete
        ...    project=${project}
        ...    defect_id=${defect_id}
        ...    body={"defect": {"status": "In Arbeit", "classification": "Bug", "priority": "High", "lastEdited": "2026-01-07T07:45:00.000Z", "principal": { "username": "arivera_dev", "password": "hashed_password_example_123" }},"syncContext": ${syncContext}}
    END
