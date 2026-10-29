package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.entity.Director;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.InvestigatorAction;
import catchmeifyoucan.entity.InvestigatorActionType;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import catchmeifyoucan.repository.InvestigatorActionRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class InvestigatorCandidateServiceTest {

    @Mock private InvestigatorActionRepository actionRepository;
    @Mock private CompanyDirectorRepository companyDirectorRepository;

    @Test
    void resolvesScenarioAndPersistedEvidenceCompaniesOnly() {
        FraudScenario scenario = scenario(1L, 10L, 11L);
        Company observed = company(12L);
        Company connected = company(13L);
        Director director = new Director("Director");
        ReflectionTestUtils.setField(director, "id", 7L);

        InvestigatorAction observation = action(InvestigatorActionType.OBSERVE_COMPANY, observed);
        InvestigatorAction investigation = action(InvestigatorActionType.INVESTIGATE_DIRECTORS,
                company(10L));
        InvestigatorAction trace = action(InvestigatorActionType.TRACE_TRANSACTION, null);
        Transaction transaction = new Transaction();
        transaction.setScenario(scenario);
        transaction.setSourceCompany(company(14L));
        transaction.setDestinationCompany(company(15L));
        trace.setTransaction(transaction);

        CompanyDirector first = new CompanyDirector(company(10L), director);
        CompanyDirector second = new CompanyDirector(connected, director);
        when(actionRepository.findByScenarioId(1L))
                .thenReturn(List.of(observation, investigation, trace));
        when(companyDirectorRepository.findByCompanyId(10L)).thenReturn(List.of(first));
        when(companyDirectorRepository.findByDirectorId(7L)).thenReturn(List.of(first, second));

        Set<Long> ids = new InvestigatorCandidateService(
                actionRepository, companyDirectorRepository).resolveCompanyIds(scenario);

        assertEquals(Set.of(10L, 11L, 12L, 13L, 14L, 15L), ids);
    }

    private FraudScenario scenario(Long id, Long sourceId, Long targetId) {
        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", id);
        scenario.setSourceCompany(company(sourceId));
        scenario.setTargetCompany(company(targetId));
        return scenario;
    }

    private InvestigatorAction action(InvestigatorActionType type, Company company) {
        InvestigatorAction action = new InvestigatorAction();
        action.setActionType(type);
        action.setTargetCompany(company);
        return action;
    }

    private Company company(Long id) {
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", id);
        return company;
    }
}
