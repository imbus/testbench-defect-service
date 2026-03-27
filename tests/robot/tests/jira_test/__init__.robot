*** Settings ***
Resource            ../../resources/service_setup.robot

Suite Setup         Start Defect Service    JiraDefectClient    jira.toml
Suite Teardown      Stop Defect Service
