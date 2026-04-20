# Contributing

Thank you for considering contributing to TestBench Defect Service! We appreciate your help in making this project even better. Please take a moment to read through this guide to understand how you can contribute effectively.

## Development Setup

To get started with development, follow these steps to clone the repository and set up your environment.

**1. Fork the repository**

Start by forking the repository to your own account.

**2.  Clone your forked repository**

After forking, clone your forked version of the repository to your local machine.

**3. Set up the virtual environment**

We provide a script to automatically set up the virtual environment and install all the necessary dependencies.

Run the following command from the project’s root directory:

```bash
python bootstrap.py
```

The script `bootstrap.py` creates a virtual environment and installs both development and test dependencies.

**4. Activate the virtual environment**

Once the setup is complete, activate the virtual environment:
- on macOS/Linux:
    ```bash
    source .venv/bin/activate
    ```
- on Windows:
    ```powershell
    .venv\Scripts\activate
    ```
 
## Running Tests

If you want to contribute code, it's important to ensure that everything works correctly. You can run the tests to make sure the code passes all the required checks.

**Run the unit tests (pytest):**
```bash
pytest tests/unit
```

**Run the Robot Framework Tests**

To run the tests, simply execute the following from the project’s root directory:

```bash
robot tests/robot/
```

This will automatically discover and run all robot tests in the project.

## Code Style & Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [mypy](https://mypy-lang.org/) for static type checking.

**Check linting:**
```bash
ruff check src/
```

**Check types:**
```bash
mypy src/
```

**Pre-commit hooks** (run automatically on each commit after setup):
```bash
pre-commit install
```

Please ensure `ruff` and `mypy` pass with no errors before opening a pull request.

## Branching & Pull Requests

1. **Create a branch** from `main` with a descriptive name:
   - `feature/<short-description>` for new features
   - `fix/<short-description>` for bug fixes
   - `docs/<short-description>` for documentation changes

2. **Commit** your changes with clear, concise commit messages.

3. **Push** your branch and open a pull request against `main`.

4. Fill in the pull request description, referencing any related issues (e.g. `Closes #42`).

5. Ensure all CI checks pass before requesting a review.

## Reporting Bugs

Please open a [GitHub Issue](https://github.com/imbus/testbench-defect-service/issues) and include:

- **Version** — output of `testbench-defect-service --version`
- **Python version** — output of `python --version`
- **Operating system**
- **Steps to reproduce** the problem (for bugs)
- **Expected vs actual behavior**

## Requesting Features

Open a [GitHub Issue](https://github.com/imbus/testbench-defect-service/issues) and describe:

- The use case you are trying to solve.
- How you imagine the feature working.
- Any alternatives you have considered.