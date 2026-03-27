*** Settings ***
Resource            ../../resources/service_setup.robot

Suite Setup         Start Defect Service    JsonlDefectClient    config_jsonl.toml
Suite Teardown      Stop Defect Service
