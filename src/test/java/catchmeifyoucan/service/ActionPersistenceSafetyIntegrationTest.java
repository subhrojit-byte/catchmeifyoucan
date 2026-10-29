package catchmeifyoucan.service;

import catchmeifyoucan.dto.FraudsterActionRequest;
import catchmeifyoucan.dto.InvestigatorActionRequest;
import catchmeifyoucan.dto.InvestigatorActionResponse;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudAction;
import catchmeifyoucan.entity.FraudActionType;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.entity.FraudPosition;
import catchmeifyoucan.entity.InvestigatorActionType;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudActionRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.InvestigatorActionRepository;
import catchmeifyoucan.repository.TransactionRepository;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

@SpringBootTest(properties = "simulation.fraud.max-turns=2")
@Transactional
class ActionPersistenceSafetyIntegrationTest {

    @Autowired private CompanyRepository companyRepository;
    @Autowired private FraudScenarioRepository scenarioRepository;
    @Autowired private FraudActionRepository fraudActionRepository;
    @Autowired private InvestigatorActionRepository investigatorActionRepository;
    @Autowired private TransactionRepository transactionRepository;
    @Autowired private FraudScenarioService scenarioService;
    @Autowired private FraudsterActionService fraudsterActionService;
    @Autowired private InvestigatorActionService investigatorActionService;
    @PersistenceContext private EntityManager entityManager;

    @Test
    void objectiveAchievementDoesNotPreventAnotherFraudsterTurnInSameScenario() {
        Company source = company("lifecycle-source");
        Company target = company("lifecycle-target");
        FraudScenario scenario = scenarioService.createScenario(source, target, BigDecimal.TEN);
        scenarioRepository.flush();

        FraudsterActionRequest fraudsterRequest = new FraudsterActionRequest();
        fraudsterRequest.setScenarioId(scenario.getId());
        fraudsterRequest.setSourcePositionId(scenario.getPositions().get(0).getId());
        fraudsterRequest.setActionType(FraudActionType.DIRECT_TRANSFER);
        FraudAction action = fraudsterActionService.createAction(fraudsterRequest);
        fraudsterActionService.executeAction(action.getId());

        FraudScenario afterTransfer = reloadScenario(scenario.getId());
        assertEquals(true, afterTransfer.getFinancialObjectiveAchieved());
        assertEquals("ACTIVE", afterTransfer.getStatus());
        assertEquals(FraudTurn.INVESTIGATOR, afterTransfer.getTurn());
        assertEquals(3, afterTransfer.getInvestigatorActionsRemaining());

        List<InvestigatorActionType> investigatorPhase = List.of(
                InvestigatorActionType.OBSERVE_COMPANY,
                InvestigatorActionType.INVESTIGATE_DIRECTORS,
                InvestigatorActionType.FLAG_COMPANY
        );
        for (int index = 0; index < investigatorPhase.size(); index++) {
            investigatorAction(scenario, investigatorPhase.get(index), target);

            FraudScenario afterInvestigatorAction = reloadScenario(scenario.getId());
            assertEquals(true, afterInvestigatorAction.getFinancialObjectiveAchieved());
            int expectedRemaining = 2 - index;
            assertEquals(expectedRemaining,
                    afterInvestigatorAction.getInvestigatorActionsRemaining());
            if (expectedRemaining > 0) {
                assertEquals("ACTIVE", afterInvestigatorAction.getStatus());
                assertEquals(FraudTurn.INVESTIGATOR, afterInvestigatorAction.getTurn());
            } else {
                assertEquals("ACTIVE", afterInvestigatorAction.getStatus());
                assertEquals(FraudTurn.FRAUDSTER, afterInvestigatorAction.getTurn());
            }
        }

        catchmeifyoucan.entity.InvestigatorAction recordedFlag =
                investigatorActionRepository.findByScenarioId(scenario.getId()).stream()
                        .filter(recorded -> recorded.getActionType() == InvestigatorActionType.FLAG_COMPANY)
                        .findFirst().orElseThrow();
        assertEquals(false, recordedFlag.getFlagCorrect());

        FraudPosition targetPosition = reloadScenario(scenario.getId()).getPositions().stream()
                .filter(position -> position.getCompany().getId().equals(target.getId()))
                .findFirst().orElseThrow();
        FraudsterActionRequest nextTurn = new FraudsterActionRequest();
        nextTurn.setScenarioId(scenario.getId());
        nextTurn.setSourcePositionId(targetPosition.getId());
        nextTurn.setActionType(FraudActionType.WAIT);
        FraudAction secondAction = fraudsterActionService.createAction(nextTurn);
        fraudsterActionService.executeAction(secondAction.getId());
        FraudScenario afterSecondTurn = reloadScenario(scenario.getId());
        assertEquals(2, afterSecondTurn.getStep());
        assertEquals("ACTIVE", afterSecondTurn.getStatus());
        assertEquals(FraudTurn.INVESTIGATOR, afterSecondTurn.getTurn());
    }

    @Test
    void staleAndWrongTurnFraudsterActionsDoNotPersistStateChanges() {
        Company source = company("safety-source");
        Company target = company("safety-target");
        FraudScenario scenario = scenarioService.createScenario(source, target, BigDecimal.TEN);
        Long positionId = scenario.getPositions().get(0).getId();

        FraudsterActionRequest request = new FraudsterActionRequest();
        request.setScenarioId(scenario.getId());
        request.setSourcePositionId(positionId);
        request.setActionType(FraudActionType.DIRECT_TRANSFER);
        FraudAction action = fraudsterActionService.createAction(request);

        int actionsBefore = fraudActionRepository.findAll().size();
        long transactionsBefore = transactionRepository.count();
        scenario.setStep(scenario.getStep() + 1);
        scenarioRepository.saveAndFlush(scenario);

        assertThrows(IllegalArgumentException.class,
                () -> fraudsterActionService.executeAction(action.getId()));

        FraudScenario unchanged = scenarioRepository.findById(scenario.getId()).orElseThrow();
        assertEquals(BigDecimal.TEN, unchanged.getPositions().get(0).getAmount());
        assertEquals(actionsBefore, fraudActionRepository.findAll().size());
        assertEquals(transactionsBefore, transactionRepository.count());

        unchanged.setStep(0);
        unchanged.setTurn(FraudTurn.INVESTIGATOR);
        scenarioRepository.saveAndFlush(unchanged);
        assertThrows(IllegalArgumentException.class,
                () -> fraudsterActionService.executeAction(action.getId()));
        assertEquals(transactionsBefore, transactionRepository.count());
    }

    @Test
    void correctFlagTerminatesAndPersistsWithoutExposingHiddenLabels() throws Exception {
        Company source = company("correct-flag-source");
        Company shellTarget = company("correct-flag-target", true);
        FraudScenario scenario = scenarioService.createScenario(source, shellTarget, BigDecimal.TEN);
        executeWait(scenario, scenario.getPositions().get(0).getId());

        InvestigatorActionResponse response = investigatorAction(
                scenario, InvestigatorActionType.FLAG_COMPANY, shellTarget);

        FraudScenario persisted = reloadScenario(scenario.getId());
        assertEquals("COMPLETED", persisted.getStatus());
        assertEquals(2, persisted.getInvestigatorActionsRemaining());
        String responseJson = new ObjectMapper().writeValueAsString(response);
        assertFalse(responseJson.contains("shellCompany"));
        assertFalse(responseJson.contains("flagCorrect"));

        InvestigatorActionRequest retry = new InvestigatorActionRequest();
        retry.setScenarioId(scenario.getId());
        retry.setActionType(InvestigatorActionType.OBSERVE_COMPANY);
        retry.setCompanyId(shellTarget.getId());
        assertThrows(IllegalArgumentException.class,
                () -> investigatorActionService.submitAction(retry));
        assertEquals("COMPLETED", reloadScenario(scenario.getId()).getStatus());
    }

    @Test
    void incorrectFlagUsesActionBudgetAndAllowsTheNextFraudsterTurn() {
        Company source = company("incorrect-flag-source");
        Company target = company("incorrect-flag-target");
        FraudScenario scenario = scenarioService.createScenario(source, target, BigDecimal.TEN);
        executeWait(scenario, scenario.getPositions().get(0).getId());

        investigatorAction(scenario, InvestigatorActionType.FLAG_COMPANY, target);
        FraudScenario afterIncorrectFlag = reloadScenario(scenario.getId());
        assertEquals("ACTIVE", afterIncorrectFlag.getStatus());
        assertEquals(FraudTurn.INVESTIGATOR, afterIncorrectFlag.getTurn());
        assertEquals(2, afterIncorrectFlag.getInvestigatorActionsRemaining());

        investigatorAction(scenario, InvestigatorActionType.OBSERVE_COMPANY, target);
        investigatorAction(scenario, InvestigatorActionType.OBSERVE_COMPANY, target);
        FraudScenario afterPhase = reloadScenario(scenario.getId());
        assertEquals("ACTIVE", afterPhase.getStatus());
        assertEquals(0, afterPhase.getInvestigatorActionsRemaining());
        assertEquals(FraudTurn.FRAUDSTER, afterPhase.getTurn());

        Long fundedSourceId = afterPhase.getPositions().stream()
                .filter(position -> position.getCompany().getId().equals(source.getId()))
                .findFirst().orElseThrow().getId();
        executeWait(afterPhase, fundedSourceId);
        FraudScenario afterNextFraudsterAction = reloadScenario(scenario.getId());
        assertEquals(2, afterNextFraudsterAction.getStep());
        assertEquals(FraudTurn.INVESTIGATOR, afterNextFraudsterAction.getTurn());
        assertEquals("ACTIVE", afterNextFraudsterAction.getStatus());
    }

    @Test
    void configuredTurnLimitPersistsDistinctTerminalOutcomeAfterCompleteCycles() {
        Company source = company("turn-limit-source");
        Company target = company("turn-limit-target");
        FraudScenario scenario = scenarioService.createScenario(source, target, BigDecimal.TEN);

        for (int cycle = 0; cycle < 2; cycle++) {
            FraudScenario beforeFraudster = reloadScenario(scenario.getId());
            Long fundedSourceId = beforeFraudster.getPositions().stream()
                    .filter(position -> position.getCompany().getId().equals(source.getId()))
                    .findFirst().orElseThrow().getId();
            executeWait(beforeFraudster, fundedSourceId);
            for (int action = 0; action < 3; action++) {
                investigatorAction(scenario, InvestigatorActionType.OBSERVE_COMPANY, target);
            }
        }

        FraudScenario terminal = reloadScenario(scenario.getId());
        assertEquals(2, terminal.getStep());
        assertEquals("MAX_TURNS_REACHED", terminal.getStatus());
        assertEquals(false, terminal.getFinancialObjectiveAchieved());
        assertEquals(FraudTurn.INVESTIGATOR, terminal.getTurn());
        assertEquals(0, terminal.getInvestigatorActionsRemaining());
    }

    @Test
    void duplicateFlagDoesNotPersistAnotherActionOrConsumeAnAction() {
        Company source = company("duplicate-source");
        Company target = company("duplicate-target");
        FraudScenario scenario = scenarioService.createScenario(source, target, BigDecimal.TEN);
        scenario.setTurn(FraudTurn.INVESTIGATOR);
        scenario.setInvestigatorActionsRemaining(3);
        scenarioRepository.saveAndFlush(scenario);

        InvestigatorActionRequest request = new InvestigatorActionRequest();
        request.setScenarioId(scenario.getId());
        request.setActionType(InvestigatorActionType.FLAG_COMPANY);
        request.setCompanyId(target.getId());

        investigatorActionService.submitAction(request);
        long actionCount = investigatorActionRepository.count();
        FraudScenario afterFirst = scenarioRepository.findById(scenario.getId()).orElseThrow();

        assertThrows(IllegalArgumentException.class,
                () -> investigatorActionService.submitAction(request));

        FraudScenario afterDuplicate = scenarioRepository.findById(scenario.getId()).orElseThrow();
        assertEquals(actionCount, investigatorActionRepository.count());
        assertEquals(afterFirst.getInvestigatorActionsRemaining(),
                afterDuplicate.getInvestigatorActionsRemaining());
        assertEquals(afterFirst.getTurn(), afterDuplicate.getTurn());
        assertEquals(afterFirst.getStatus(), afterDuplicate.getStatus());
    }

    @Test
    void insufficientFundsDoesNotPersistAnAction() {
        Company source = company("insufficient-source");
        Company target = company("insufficient-target");
        FraudScenario scenario = scenarioService.createScenario(source, target, BigDecimal.TEN);
        scenario.getPositions().get(0).setAmount(BigDecimal.ZERO);
        scenarioRepository.saveAndFlush(scenario);

        FraudsterActionRequest request = new FraudsterActionRequest();
        request.setScenarioId(scenario.getId());
        request.setSourcePositionId(scenario.getPositions().get(0).getId());
        request.setActionType(FraudActionType.DIRECT_TRANSFER);

        long actionsBefore = fraudActionRepository.count();
        assertThrows(IllegalArgumentException.class,
                () -> fraudsterActionService.createAction(request));
        assertEquals(actionsBefore, fraudActionRepository.count());
        assertEquals(BigDecimal.ZERO,
                scenarioRepository.findById(scenario.getId()).orElseThrow()
                        .getPositions().get(0).getAmount());
    }

    private Company company(String name) {
        return company(name, false);
    }

    private Company company(String name, boolean shellCompany) {
        Company company = new Company();
        company.setCompanyName(name);
        company.setShellCompany(shellCompany);
        return companyRepository.saveAndFlush(company);
    }

    private FraudAction executeWait(FraudScenario scenario, Long sourcePositionId) {
        FraudsterActionRequest request = new FraudsterActionRequest();
        request.setScenarioId(scenario.getId());
        request.setSourcePositionId(sourcePositionId);
        request.setActionType(FraudActionType.WAIT);
        FraudAction action = fraudsterActionService.createAction(request);
        fraudsterActionService.executeAction(action.getId());
        return action;
    }

    private InvestigatorActionResponse investigatorAction(
            FraudScenario scenario, InvestigatorActionType type, Company company) {
        InvestigatorActionRequest request = new InvestigatorActionRequest();
        request.setScenarioId(scenario.getId());
        request.setActionType(type);
        request.setCompanyId(company.getId());
        return investigatorActionService.submitAction(request);
    }

    private FraudScenario reloadScenario(Long scenarioId) {
        scenarioRepository.flush();
        entityManager.clear();
        return scenarioRepository.findById(scenarioId).orElseThrow();
    }
}
