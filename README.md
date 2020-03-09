Cloud factory for the accurate materials data
==========

using the MPDS data platform, AiiDA workflows, and CRYSTAL simulation engine.

![MPDS](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/mpds.png "MPDS + AiiDA + CRYSTAL") + ![AiiDA](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/aiida.png "AiiDA + MPDS + CRYSTAL") + ![CRYSTAL](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/crystal.jpg "CRYSTAL + MPDS + AiiDA")


## Rationale

- get vast systematic training data for machine learning
- get high-quality reference, encyclopedic, and benchmarking data
- use the cheap commodity cloud (_not_ HPC cluster) environment


## Installation

The code in this repo requires the [aiida-crystal](https://github.com/tilde-lab/aiida-crystal), [yascheduler](https://github.com/tilde-lab/yascheduler), and [mpds-ml-labs](https://github.com/mpds-io/mpds-ml-labs) Python packages installed. In their turn, they depend on the [aiida](https://github.com/aiidateam/aiida-core), [mpds_client](https://github.com/mpds-io/mpds_client), and other Python packages.

Thus, installation is as follows:

```shell
>> pip install git+https://github.com/tilde-lab/aiida-crystal
>> pip install git+https://github.com/tilde-lab/yascheduler
>> pip install git+https://github.com/mpds-io/mpds-ml-labs
>> git clone https://github.com/mpds-io/mpds-aiida
>> pip install mpds-aiida/
```

Here some reader's AiiDA experience is assumed. Note, that the AiiDA as of *version 1.1.0* does _not_ support cloud environments, so the custom cloud scheduler engine [yascheduler](https://github.com/tilde-lab/yascheduler) has to be used. This scheduler manages the [CRYSTAL](http://www.crystal.unito.it) simulation engine at the cloud VPS instances and encapsulates all the details, concerning the remote *computer* task submission, queue, and results retrieval, as well as the VPS management. The AiiDA should be set up normally, and the stub remote *computer* (_e.g._ `cluster: yascheduler`), as well as the stub CRYSTAL *code* (_e.g._ `codes: Pcrystal`) should be added:

```shell
>> reentry scan
>> verdi computer setup
>> verdi code setup
```

The Gaussian basis sets used by CRYSTAL engine should be added to the AiiDA database. We download the entire basis set library from the CRYSTAL website and save some basis sets as `*.basis` files using the script `bin/run_get_unito_bsl.py`. Then, in a subfolder with the `*.basis` files, one runs:

```shell
>> verdi data crystal uploadfamily --name=BASIS_FAMILY
```

or, to add the internal basis sets predefined in CRYSTAL:

```shell
>> verdi data crystal createpredefined
```

A template system is used to control the calculation parameters, see the `mpds_aiida/calc_templates` subfolder. Note, that the `options: resources` template directive makes no sense with our custom cloud scheduler, and the `cluster`, `codes`, and `basis_family` template directives have to be specified exactly as defined above.


## Usage

An operation principle is briefly illustrated below.

![General workflow](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/workflow.png "General workflow")

More examples are given in the `bin` subfolder.

Note: this repo is subject to change and presents an ongoing work in progress.


## Licensing

Code: [MIT](https://en.wikipedia.org/wiki/MIT_License)

The resulting data are available at the [MPDS platform](https://mpds.io/search/ab%20initio%20calculations), according to the CC BY 4.0 license.