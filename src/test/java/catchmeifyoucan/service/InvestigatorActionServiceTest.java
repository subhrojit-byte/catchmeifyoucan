package catchmeifyoucan.service;

import catchmeifyoucan.dto.InvestigatorActionRequest;
import catchmeifyoucan.dto.InvestigatorActionResponse;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.entity.InvestigatorAction;
import catchmeifyoucan.entity.InvestigatorActionType;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.InvestigatorActionRepository;
import catchmeifyoucan.repository.TransactionRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Optional;
import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import org.mockito.ArgumentCaptor;

@ExtendWith(MockitoExtension.class)
class InvestigatorActionServiceTest {

    @Mock private FraudScenarioRepository scenarioRepository;
    @Mock private InvestigatorActionRepository actionRepository;
    @Mock private CompanyRepository companyRepository;
    @Mock private TransactionRepository transactionRepository;
    @Mock private CompanyDirectorRepository companyDirectorRepository;

    @Test
    void threeInvestigatorActionsReturnTheTurnToTheFraudster() {
        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", 1L);
        scenario.setStatus("ACTIVE");
        scenario.setStep(2);
        scenario.setTurn(FraudTurn.INVESTIGATOR);
        scenario.setInvestigatorActionsRemaining(3);
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", 2L);

        when(scenarioRepository.findById(1L)).thenReturn(Optional.of(scenario));
        when(companyRepository.findById(2L)).thenReturn(Optional.of(company));
        lenient().when(actionRepository.save(any(InvestigatorAction.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        InvestigatorActionService service = new InvestigatorActionService(scenarioRepository,
                actionRepository, companyRepository, transactionRepository, companyDirectorRepository);
        for (int i = 0; i < 3; i++) {
            InvestigatorActionRequest request = new InvestigatorActionRequest();
            request.setScenarioId(1L);
            request.setActionType(InvestigatorActionType.OBSERVE_COMPANY);
            request.setCompanyId(2L);
            service.submitAction(request);
        }

        assertEquals(0, scenario.getInvestigatorActionsRemaining());
        assertEquals(FraudTurn.FRAUDSTER, scenario.getTurn());
    }

    @Test
    void finalInvestigatorActionReturnsTurnEvenWhenObjectiveWasAchieved() {
        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", 1L);
        scenario.setStatus("ACTIVE");
        scenario.setStep(2);
        scenario.setTurn(FraudTurn.INVESTIGATOR);
        scenario.setInvestigatorActionsRemaining(3);
        scenario.setFinancialObjectiveAchieved(true);
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", 2L);

        when(scenarioRepository.findById(1L)).thenReturn(Optional.of(scenario));
        when(companyRepository.findById(2L)).thenReturn(Optional.of(company));
        lenient().when(actionRepository.save(any(InvestigatorAction.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        InvestigatorActionService service = new InvestigatorActionService(scenarioRepository,
                actionRepository, companyRepository, transactionRepository, companyDirectorRepository);
        for (int i = 0; i < 3; i++) {
            InvestigatorActionRequest request = new InvestigatorActionRequest();
            request.setScenarioId(1L);
            request.setActionType(InvestigatorActionType.OBSERVE_COMPANY);
            request.setCompanyId(2L);
            service.submitAction(request);
        }

        assertEquals("ACTIVE", scenario.getStatus());
        assertEquals(0, scenario.getInvestigatorActionsRemaining());
        assertEquals(FraudTurn.FRAUDSTER, scenario.getTurn());
    }

    @Test
    void shellCompanyFlagIsPersistedWithoutReturningCorrectness() throws Exception {
        FraudScenario scenario = scenario();
        Company company = company(2L, true);
        InvestigatorActionService service = service(scenario, company, false);

        InvestigatorActionRequest request = flagRequest();
        InvestigatorActionResponse response = service.submitAction(request);

        assertEquals(2, scenario.getInvestigatorActionsRemaining());
        assertFalse(Arrays.stream(response.getClass().getDeclaredFields())
                .anyMatch(field -> field.getName().equals("shellCompany")));
        assertFalse(Arrays.stream(response.getClass().getDeclaredFields())
                .anyMatch(field -> field.getName().equals("flagCorrect")));
        ArgumentCaptor<InvestigatorAction> captor = ArgumentCaptor.forClass(InvestigatorAction.class);
        verify(actionRepository).save(captor.capture());
        assertEquals(true, captor.getValue().getFlagCorrect());
        assertEquals("COMPLETED", scenario.getStatus());
        assertEquals(2, scenario.getInvestigatorActionsRemaining());
    }

    @Test
    void legitimateCompanyFlagIsPersistedAsIncorrectAndDoesNotTerminateScenario() {
        FraudScenario scenario = scenario();
        Company company = company(2L, false);
        InvestigatorActionService service = service(scenario, company, false);

        InvestigatorActionResponse response = service.submitAction(flagRequest());

        ArgumentCaptor<InvestigatorAction> captor = ArgumentCaptor.forClass(InvestigatorAction.class);
        verify(actionRepository).save(captor.capture());
        assertEquals(false, captor.getValue().getFlagCorrect());
        assertEquals("ACTIVE", scenario.getStatus());
        assertEquals(FraudTurn.INVESTIGATOR, scenario.getTurn());
        assertEquals(2, scenario.getInvestigatorActionsRemaining());
    }

    @Test
    void reachingConfiguredTurnLimitUsesDistinctTerminalStatus() {
        FraudScenario scenario = scenario();
        scenario.setStep(1);
        Company company = company(2L, false);
        InvestigatorActionService service = service(scenario, company, false);
        ReflectionTestUtils.setField(service, "maxFraudsterTurns", 1);
        for (int i = 0; i < 3; i++) {
            InvestigatorActionRequest request = new InvestigatorActionRequest();
            request.setScenarioId(1L);
            request.setActionType(InvestigatorActionType.OBSERVE_COMPANY);
            request.setCompanyId(2L);
            service.submitAction(request);
        }
        assertEquals("MAX_TURNS_REACHED", scenario.getStatus());
        assertEquals(FraudTurn.INVESTIGATOR, scenario.getTurn());
        assertEquals(false, scenario.getFinancialObjectiveAchieved());
    }

    @Test
    void duplicateFlagIsRejectedWithoutConsumingAction() {
        FraudScenario scenario = scenario();
        Company company = company(2L, true);
        InvestigatorActionService service = service(scenario, company, true);

        assertThrows(IllegalArgumentException.class, () -> service.submitAction(flagRequest()));

        assertEquals(3, scenario.getInvestigatorActionsRemaining());
        assertEquals(FraudTurn.INVESTIGATOR, scenario.getTurn());
        assertEquals("ACTIVE", scenario.getStatus());
        verify(actionRepository, never()).save(any(InvestigatorAction.class));
    }

    @Test
    void unrelatedTraceIsRejectedWithoutConsumingAction() {
        FraudScenario scenario = scenario();
        Company unrelated = company(99L, false);
        Transaction transaction = new Transaction();
        transaction.setScenario(otherScenario(2L));
        transaction.setSourceCompany(unrelated);
        transaction.setDestinationCompany(company(100L, false));
        when(scenarioRepository.findById(1L)).thenReturn(Optional.of(scenario));
        when(transactionRepository.findById(77L)).thenReturn(Optional.of(transaction));

        InvestigatorActionService service = new InvestigatorActionService(
                scenarioRepository, actionRepository, companyRepository,
                transactionRepository, companyDirectorRepository);
        InvestigatorActionRequest request = new InvestigatorActionRequest();
        request.setScenarioId(1L);
        request.setActionType(InvestigatorActionType.TRACE_TRANSACTION);
        request.setTransactionId(77L);

        assertThrows(IllegalArgumentException.class, () -> service.submitAction(request));
        assertEquals(3, scenario.getInvestigatorActionsRemaining());
        verify(actionRepository, never()).save(any(InvestigatorAction.class));
    }

    @Test
    void unobservedFlagTargetIsRejectedWithoutConsumingAction() {
        FraudScenario scenario = scenario();
        Company unobserved = company(99L, false);
        when(scenarioRepository.findById(1L)).thenReturn(Optional.of(scenario));
        when(companyRepository.findById(99L)).thenReturn(Optional.of(unobserved));

        InvestigatorActionService service = new InvestigatorActionService(
                scenarioRepository, actionRepository, companyRepository,
                transactionRepository, companyDirectorRepository);
        InvestigatorActionRequest request = new InvestigatorActionRequest();
        request.setScenarioId(1L);
        request.setActionType(InvestigatorActionType.FLAG_COMPANY);
        request.setCompanyId(99L);

        assertThrows(IllegalArgumentException.class, () -> service.submitAction(request));
        assertEquals(3, scenario.getInvestigatorActionsRemaining());
        verify(actionRepository, never()).save(any(InvestigatorAction.class));
    }

    private InvestigatorActionService service(FraudScenario scenario, Company company,
                                              boolean duplicate) {
        when(scenarioRepository.findById(1L)).thenReturn(Optional.of(scenario));
        when(companyRepository.findById(2L)).thenReturn(Optional.of(company));
        lenient().when(actionRepository.existsByScenarioIdAndActionTypeAndTargetCompanyId(
                1L, InvestigatorActionType.FLAG_COMPANY, 2L)).thenReturn(duplicate);
        lenient().when(actionRepository.save(any(InvestigatorAction.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        return new InvestigatorActionService(scenarioRepository, actionRepository,
                companyRepository, transactionRepository, companyDirectorRepository);
    }

    private InvestigatorActionRequest flagRequest() {
        InvestigatorActionRequest request = new InvestigatorActionRequest();
        request.setScenarioId(1L);
        request.setActionType(InvestigatorActionType.FLAG_COMPANY);
        request.setCompanyId(2L);
        return request;
    }

    private FraudScenario scenario() {
        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", 1L);
        scenario.setStatus("ACTIVE");
        scenario.setStep(0);
        scenario.setTurn(FraudTurn.INVESTIGATOR);
        scenario.setInvestigatorActionsRemaining(3);
        scenario.setSourceCompany(company(1L, false));
        scenario.setTargetCompany(company(2L, false));
        return scenario;
    }

    private FraudScenario otherScenario(Long id) {
        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", id);
        return scenario;
    }

    private Company company(Long id, boolean shell) {
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", id);
        company.setShellCompany(shell);
        return company;
    }
}
