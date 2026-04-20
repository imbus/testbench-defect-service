*** Settings ***
Resource            ../../resources/service_setup.robot

Suite Setup         Start Defect Service    JiraDefectClient    jira_readonly.toml
Suite Teardown      Stop Defect Service
