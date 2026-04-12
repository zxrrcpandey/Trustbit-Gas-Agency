from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

with open("trustbit_gas_agency/__init__.py") as f:
    for line in f:
        if line.startswith("__version__"):
            version = line.split("=")[1].strip().strip('"').strip("'")
            break

setup(
    name="trustbit_gas_agency",
    version=version,
    description="Gas Agency Management for Cylinder Exchange and Multi-Location Tracking",
    author="Trustbit Software",
    author_email="info@trustbit.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
