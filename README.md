Ab initio materials genomics: cloud factory of highly accurate data
==========

![MPDS + AiiDA + CRYSTAL](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/logo.jpg "MPDS + AiiDA + CRYSTAL")

A giant amount of systematic training data is required for the machine learning. These data must be also of very high quality (garbage in means garbage out). We present a cloud factory for generating such high-quality data for the materials properties via the electron-structure simulations with the CRYSTAL code.

The code in this repo uses [aiida-crystal](https://github.com/tilde-lab/aiida-crystal), [yascheduler](https://github.com/tilde-lab/yascheduler), [mpds-ml-labs](https://github.com/mpds-io/mpds-ml-labs), and other Python libraries:

```
    pip install git+https://github.com/tilde-lab/aiida-crystal
    pip install git+https://github.com/tilde-lab/yascheduler
    pip install git+https://github.com/mpds-io/mpds-ml-labs
```

![General workflow](https://raw.githubusercontent.com/mpds-io/mpds-aiida/master/workflow.png "General workflow")

This repo presents the work in progress. The resulting data are [available](https://mpds.io/#search/ab%20initio%20calculations) according to the CC BY 4.0 license.