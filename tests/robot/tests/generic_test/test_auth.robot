*** Settings ***
Library     ../../resources/APIKeywords.py


*** Test Cases ***
Get Check Login Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Check Login    assertion_operator=validate    assertion_expected= value.status_code == 401

Get Check Login 403 With Invalid Auth
    Set Credentials    username=user    password=${EMPTY}
    Get Check Login    assertion_operator=validate    assertion_expected= value.status_code == 403

Get Settings Return 403 With Invalid Auth
    Get Settings    assertion_operator=validate    assertion_expected= value.status_code == 200

Get Projects Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Projects    assertion_operator=validate    assertion_expected= value.status_code == 401

Get Projects Return 403 With Invalid Auth
    Set Credentials    ${EMPTY}    password
    Get Projects    assertion_operator=validate    assertion_expected= value.status_code == 403

Get Project Control Fields Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Project Control Fields
    ...    defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 401

Get Project Control Fields Return 403 Invalid Auth
    Set Credentials    user    password
    Get Project Control Fields
    ...    defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 403

Get Project Defects Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Project Defects    defects    assertion_operator=validate    assertion_expected= value.status_code == 401

Get Project Defects Return 403 Invalid Auth
    Set Credentials    !    ?
    Get Project Defects    defects    assertion_operator=validate    assertion_expected= value.status_code == 403

Post Project Batch Defects Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Post Project Defect Batch    defects    assertion_operator=validate    assertion_expected= value.status_code == 401

Post Project Batch Defects Return 403 Invalid Auth
    Set Credentials    Username    ${EMPTY}
    Post Project Defect Batch    defects    assertion_operator=validate    assertion_expected= value.status_code == 403

Post Project Create Defect Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Post Project Defect Create
    ...    defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 401

Post Project Create Defect Return 403 Invalid Auth
    Set Credentials    ${EMPTY}    password
    Post Project Defect Create
    ...    defects
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 403

Put Project Update Defect Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Put Project Defect Update
    ...    defects
    ...    defect_id=BUG-1
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 401

Put Project Update Defect Return 403 Invalid Auth
    Set Credentials    Hello    World
    Put Project Defect Update
    ...    defects
    ...    defect_id=BUG-1
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 403

Post Project Delete Defect Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Post Project Defect Delete
    ...    defects
    ...    defect_id=BUG-1
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 401

Post Project Delete Defect Return 403 Invalid Auth
    Set Credentials    username    password
    Post Project Defect Delete
    ...    defects
    ...    defect_id=BUG-1
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 403

Get Project Extended Defects Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Project Extended Defects
    ...    defects
    ...    id
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 401

Get Project Extended Defects Return 403 Invalid Auth
    Set Credentials    username    password
    Get Project Extended Defects
    ...    defects
    ...    id
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 403

Get Project UDFs Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Project Udfs    defects    assertion_operator=validate    assertion_expected= value.status_code == 401

Get Project UDFs Return 403 Invalid Auth
    Set Credentials    username    password
    Get Project Udfs    defects    assertion_operator=validate    assertion_expected= value.status_code == 403

Post Project Sync Before Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Post Project Sync Before    defects    assertion_operator=validate    assertion_expected= value.status_code == 401

Post Project Sync Before Return 403 Invalid Auth
    Set Credentials    username    password
    Post Project Sync Before    defects    assertion_operator=validate    assertion_expected= value.status_code == 403

Post Project Sync After Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Post Project Sync After    defects    assertion_operator=validate    assertion_expected= value.status_code == 401

Post Project Sync After Return 403 Invalid Auth
    Set Credentials    username    password
    Post Project Sync After    defects    assertion_operator=validate    assertion_expected= value.status_code == 403

Get Supports Canges Timestamps Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Get Supports Changes Timestamps    assertion_operator=validate    assertion_expected= value.status_code == 401

Get Supports Canges Timestamps Return 403 Invalid Auth
    Set Credentials    username    password
    Get Supports Changes Timestamps    assertion_operator=validate    assertion_expected= value.status_code == 403

Post Correct Defects Return 401 Without Auth
    Set Credentials    ${EMPTY}    ${EMPTY}
    Post Correct Defects
    ...    project=project
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 401

Post Correct Defects Return 403 Invalid Auth
    Set Credentials    username    password
    Post Correct Defects
    ...    project=project
    ...    assertion_operator=validate
    ...    assertion_expected= value.status_code == 403
