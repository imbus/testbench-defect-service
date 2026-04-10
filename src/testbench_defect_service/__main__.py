import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from testbench_defect_service.cli import cli

    cli()
