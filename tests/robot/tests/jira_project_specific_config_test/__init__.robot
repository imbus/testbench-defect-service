*** Settings ***
Resource            ../../resources/service_setup.robot

Suite Setup         Start Defect Service    JiraDefectClient    jira_projects_comfig.toml
Suite Teardown      Stop Defect Service
