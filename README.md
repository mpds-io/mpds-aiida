Cloud factory for the accurate materials data
==========

using the MPDS data platform, AiiDA workflows, and CRYSTAL simulation engine.

![MPDS](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/mpds.png "MPDS + AiiDA + CRYSTAL") ![AiiDA](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/aiida.png "AiiDA + MPDS + CRYSTAL") ![CRYSTAL](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/crystal.jpg "CRYSTAL + MPDS + AiiDA")

## Rationale

- systematic training data for machine learning
- reference, encyclopedic, and benchmarking data

## Usage

The code in this repo requires the [aiida-crystal](https://github.com/tilde-lab/aiida-crystal), [yascheduler](https://github.com/tilde-lab/yascheduler), and [mpds-ml-labs](https://github.com/mpds-io/mpds-ml-labs) Python packages installed:

```
pip install git+https://github.com/tilde-lab/aiida-crystal
pip install git+https://github.com/tilde-lab/yascheduler
pip install git+https://github.com/mpds-io/mpds-ml-labs
```

In their turn, they depend on [aiida](https://github.com/aiidateam/aiida-core), [mpds_client](https://github.com/mpds-io/mpds_client), and other Python packages.

![General workflow](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/workflow.png "General workflow")

This repo presents work in progress.

## Licensing

Code: [MIT](https://en.wikipedia.org/wiki/MIT_License)

The resulting data are available at the [MPDS platform](https://mpds.io/#search/ab%20initio%20calculations), according to the CC BY 4.0 license.