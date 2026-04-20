# Unit Tests

This directory contains unit tests for the testbench-defect-service project.

## Structure

```
test/unit/
├── __init__.py
├── clients/
│   ├── __init__.py
│   └── jira/
│       ├── __init__.py
│       ├── conftest.py          # Shared pytest fixtures for Jira tests
│       └── test_utils.py        # Unit tests for Jira utility functions
└── README.md
```

## Running Tests

### Requirements

Install test dependencies:

```bash
pip install -e ".[test]"
```

### Run All Unit Tests

```bash
pytest
```

### Run with Coverage

```bash
pytest --cov=src/testbench_defect_service --cov-report=html
```

Coverage report will be generated in `htmlcov/index.html`.

### Run Specific Test File

```bash
pytest test/unit/clients/jira/test_utils.py
```

### Run Specific Test Class

```bash
pytest test/unit/clients/jira/test_utils.py::TestBuildProjectDict
```

### Run Specific Test

```bash
pytest test/unit/clients/jira/test_utils.py::TestBuildProjectDict::test_build_project_dict_single_project
```

### Run with Verbose Output

```bash
pytest -v
```

### Run Only Unit Tests (marked with @pytest.mark.unit)

```bash
pytest -m unit
```

## Test Markers

- `@pytest.mark.unit` - Unit tests (fast, isolated tests)
- `@pytest.mark.integration` - Integration tests (slower, may require external services)

## Writing Tests

### File Naming Convention

- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Example Test

```python
import pytest
from testbench_defect_service.clients.jira.utils import build_project_dict


@pytest.mark.unit
class TestBuildProjectDict:
    """Tests for build_project_dict function."""

    def test_build_project_dict_single_project(self, mock_jira_project):
        """Test building dictionary from single project."""
        projects = [mock_jira_project]
        result = build_project_dict(projects)
      
        assert len(result) == 1
        assert "Test Project (TEST)" in result
```

### Using Fixtures

Shared fixtures are defined in `conftest.py` files and are automatically available to all tests in the same directory and subdirectories.

```python
def test_example(mock_jira_issue, sample_field_metadata):
    """Fixtures are automatically injected by pytest."""
    # Use the fixtures
    assert mock_jira_issue.key == "TEST-123"
```

## Continuous Integration

Tests are automatically run on:

- Pull requests
- Commits to main branch

All tests must pass before merging.

## Coverage Goals

- Target: 80% code coverage minimum
- Critical paths: 100% coverage required

## Tips

1. **Keep tests isolated**: Each test should be independent
2. **Use descriptive names**: Test names should clearly describe what they test
3. **One assertion concept per test**: Test one behavior at a time
4. **Use fixtures**: Reuse common test data and mocks
5. **Mock external dependencies**: Use mocks for Jira API, file I/O, etc.
