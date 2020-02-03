//
// Created by mho on 2/3/20.
//

#include "common.h"
#include "OutputModels.h"

using namespace pybind11::literals;

PYBIND11_MODULE(_hmm_bindings, m) {
    auto outputModels = m.def_submodule("output_models");
    {
        {
            auto discrete = m.def_submodule("discrete");
            discrete.def("update_p_out", &hmm::output_models::discrete::updatePOut<float, std::int32_t>, "obs"_a, "weights"_a, "pout"_a);
            discrete.def("update_p_out", &hmm::output_models::discrete::updatePOut<float, std::int64_t>, "obs"_a, "weights"_a, "pout"_a);
            discrete.def("update_p_out", &hmm::output_models::discrete::updatePOut<double, std::int32_t>, "obs"_a, "weights"_a, "pout"_a);
            discrete.def("update_p_out", &hmm::output_models::discrete::updatePOut<double, std::int64_t>, "obs"_a, "weights"_a, "pout"_a);
        }

        {
            auto gaussian = m.def_submodule("gaussian");
            gaussian.def("p_o", &hmm::output_models::gaussian::pO<double>, "o"_a, "mus"_a, "sigmas"_a, "out"_a = py::none());
            gaussian.def("p_o", &hmm::output_models::gaussian::pO<float>, "o"_a, "mus"_a, "sigmas"_a, "out"_a = py::none());
            gaussian.def("p_obs", &hmm::output_models::gaussian::pObs<double>, "obs"_a, "mus"_a, "sigmas"_a, "out"_a = py::none());
            gaussian.def("p_obs", &hmm::output_models::gaussian::pObs<float>, "obs"_a, "mus"_a, "sigmas"_a, "out"_a = py::none());
        }
    }
}