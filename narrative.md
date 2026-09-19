Drug development is a costly, time-consuming process marked by high failure rates. 
Despite extensive preclinical testing, many drug candidates fail to progress through clinical trials, limiting the number of new therapies that ultimately reach patients.

Toxicity remains a major cause of drug attrition. A particularly challenging issue is the emergence of adverse effects in human trials that were not detected in preclinical studies, including conventional in vitro assays. These assays cannot fully reproduce the complexity of human biology and may therefore miss toxic effects associated with drug metabolism, prolonged exposure, or interactions between different cell types and tissues.

Liver toxicity (or DILI) is the leading cause of toxicity attrition in drug development. Drug-induced liver injury can limit dosing, interrupt clinical trials, and lead to the discontinuation of otherwise promising candidates. Improving the ability of preclinical models to identify potential liver toxicity is therefore essential to support safer drug development and reduce costly failures at later stages.

We have built over this hack an agentic tool, ToxOracle, using NVIDIA BioNeMo and Rosalind/Codex that allows scientists to predict potential for DILI risk for novel compounds. This tool combines structure-based similarity predictions to known DILI drugs, and identify potential key mechanisms from structure analogs _in vitro_ data. 

The next step for this project could be to expand to other organs (i.e. looking at kidney toxicity, cardiotoxicity) or to be set up to accept end-user experimental data (such as _in vitro_ and _in vivo_ exposures). We start with the liver, with the potential to expand to other organ toxicities. 
