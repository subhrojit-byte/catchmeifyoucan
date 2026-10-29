package catchmeifyoucan.service;

import catchmeifyoucan.dto.FraudsterActionRequest;
import catchmeifyoucan.dto.FraudsterActionTargetRequest;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudAction;
import catchmeifyoucan.entity.FraudActionType;
import catchmeifyoucan.entity.FraudPosition;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudActionRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.TransactionRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.HashSet;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class FraudsterActionServiceTest {

    @Mock private FraudScenarioRepository scenarioRepository;
    @Mock private FraudActionRepository actionRepository;
    @Mock private CompanyRepository companyRepository;
    @Mock private TransactionRepository transactionRepository;
    @Mock private CompanyRelationshipService companyRelationshipService;
    @Mock private BackgroundTransactionService backgroundTransactionService;

    private FraudsterActionService service;

    @BeforeEach
    void setUp() {
        service = new FraudsterActionService(scenarioRepository, actionRepository,
                companyRepository, transactionRepository, companyRelationshipService,
                backgroundTransactionService);
    }

    @Test
    void directTransferUsesEntireBalanceAndScenarioTargetWithoutRequestTarget() {
        Fixture fixture = fixture("100.00");
        when(companyRepository.findById(fixture.target.getId())).thenReturn(Optional.of(fixture.target));

        FraudAction action = create(fixture, FraudActionType.DIRECT_TRANSFER, List.of());
        execute(fixture, action);

        assertEquals(new BigDecimal("0.00"), fixture.sourcePosition.getAmount());
        assertEquals(new BigDecimal("100.00"), positionAt(fixture.scenario, fixture.target).getAmount());
        assertEquals("ACTIVE", fixture.scenario.getStatus());
        assertEquals(true, fixture.scenario.getFinancialObjectiveAchieved());
        assertEquals(FraudTurn.INVESTIGATOR, fixture.scenario.getTurn());
        assertEquals(3, fixture.scenario.getInvestigatorActionsRemaining());
        verify(backgroundTransactionService).generateForSuccessfulAction(fixture.scenario, action);
        assertTransaction(fixture.source, fixture.target, "100.00");
    }

    @Test
    void routeTransferUsesEntireBalanceAndRequiresSeparateDirectTransfer() {
        Fixture fixture = fixture("75.50");
        when(companyRepository.findById(fixture.intermediate.getId())).thenReturn(Optional.of(fixture.intermediate));
        when(companyRepository.findById(fixture.target.getId())).thenReturn(Optional.of(fixture.target));

        FraudAction route = create(fixture, FraudActionType.ROUTE_TRANSFER,
                List.of(target(fixture.intermediate.getId(), null)));
        execute(fixture, route);

        assertEquals(new BigDecimal("0.00"), fixture.sourcePosition.getAmount());
        FraudPosition intermediatePosition = positionAt(fixture.scenario, fixture.intermediate);
        assertEquals(new BigDecimal("75.50"), intermediatePosition.getAmount());
        assertTrue(positionAt(fixture.scenario, fixture.target) == null);
        assertEquals("ACTIVE", fixture.scenario.getStatus());
        assertTransaction(fixture.source, fixture.intermediate, "75.50");

        // The investigator phase is outside this service; after it completes, a new action is needed.
        fixture.scenario.setTurn(FraudTurn.FRAUDSTER);
        ReflectionTestUtils.setField(intermediatePosition, "id", 21L);
        FraudAction direct = create(fixture, FraudActionType.DIRECT_TRANSFER, List.of(), intermediatePosition);
        execute(fixture, direct);

        assertEquals(new BigDecimal("0.00"), intermediatePosition.getAmount());
        assertEquals(new BigDecimal("75.50"), positionAt(fixture.scenario, fixture.target).getAmount());
        assertEquals("ACTIVE", fixture.scenario.getStatus());
        assertEquals(true, fixture.scenario.getFinancialObjectiveAchieved());
        verify(transactionRepository, times(2)).saveAll(any());
    }

    @Test
    void invalidRouteAndInsufficientFundsDoNotCreateActionsOrMutatePositions() {
        Fixture fixture = fixture("10.00");
        assertThrows(IllegalArgumentException.class, () -> create(fixture,
                FraudActionType.ROUTE_TRANSFER, List.of(target(fixture.target.getId(), null))));
        assertEquals(new BigDecimal("10.00"), fixture.sourcePosition.getAmount());
        verify(actionRepository, never()).save(any());

        fixture.sourcePosition.setAmount(BigDecimal.ZERO);
        assertThrows(IllegalArgumentException.class, () -> create(fixture,
                FraudActionType.DIRECT_TRANSFER, List.of()));
        verify(transactionRepository, never()).saveAll(any());
    }

    @Test
    void unrelatedRouteDestinationIsRejectedBeforeActionCreation() {
        Fixture fixture = fixture("10.00");
        when(scenarioRepository.findById(fixture.scenario.getId())).thenReturn(Optional.of(fixture.scenario));
        when(companyRelationshipService.eligibleIntermediateCompanyIds(
                fixture.source.getId(), fixture.target.getId())).thenReturn(Set.of());

        FraudsterActionRequest request = new FraudsterActionRequest();
        request.setScenarioId(fixture.scenario.getId());
        request.setActionType(FraudActionType.ROUTE_TRANSFER);
        request.setSourcePositionId(fixture.sourcePosition.getId());
        request.setTargets(List.of(target(fixture.other.getId(), null)));

        assertThrows(IllegalArgumentException.class, () -> service.createAction(request));
        assertEquals(new BigDecimal("10.00"), fixture.sourcePosition.getAmount());
        verify(actionRepository, never()).save(any());
        verify(transactionRepository, never()).saveAll(any());
    }

    @Test
    void unrelatedSplitDestinationsAreRejectedBeforeActionCreation() {
        Fixture fixture = fixture("10.00");
        when(scenarioRepository.findById(fixture.scenario.getId())).thenReturn(Optional.of(fixture.scenario));
        when(companyRelationshipService.eligibleIntermediateCompanyIds(
                fixture.source.getId(), fixture.target.getId())).thenReturn(Set.of());

        FraudsterActionRequest request = new FraudsterActionRequest();
        request.setScenarioId(fixture.scenario.getId());
        request.setActionType(FraudActionType.SPLIT_TRANSFER);
        request.setSourcePositionId(fixture.sourcePosition.getId());
        request.setTargets(List.of(
                target(fixture.other.getId(), new BigDecimal("5.00")),
                target(fixture.target.getId(), new BigDecimal("5.00"))));

        assertThrows(IllegalArgumentException.class, () -> service.createAction(request));
        assertEquals(new BigDecimal("10.00"), fixture.sourcePosition.getAmount());
        verify(actionRepository, never()).save(any());
        verify(transactionRepository, never()).saveAll(any());
    }

    @Test
    void staleAndWrongTurnActionsDoNotTransferFunds() {
        Fixture fixture = fixture("10.00");
        when(companyRepository.findById(fixture.target.getId())).thenReturn(Optional.of(fixture.target));
        FraudAction action = create(fixture, FraudActionType.DIRECT_TRANSFER, List.of());
        when(actionRepository.findById(action.getId())).thenReturn(Optional.of(action));
        when(scenarioRepository.findById(fixture.scenario.getId())).thenReturn(Optional.of(fixture.scenario));

        fixture.scenario.setStep(1);
        assertThrows(IllegalArgumentException.class, () -> service.executeAction(action.getId()));
        assertEquals(new BigDecimal("10.00"), fixture.sourcePosition.getAmount());
        verify(transactionRepository, never()).saveAll(any());
        verify(backgroundTransactionService, never())
                .generateForSuccessfulAction(any(), any());

        fixture.scenario.setTurn(FraudTurn.INVESTIGATOR);
        assertThrows(IllegalArgumentException.class, () -> create(fixture,
                FraudActionType.DIRECT_TRANSFER, List.of()));
    }

    @Test
    void splitTransferAndWaitRetainTheirExistingExecutionBehavior() {
        Fixture fixture = fixture("100.00");
        when(companyRepository.findById(fixture.intermediate.getId())).thenReturn(Optional.of(fixture.intermediate));
        when(companyRepository.findById(fixture.other.getId())).thenReturn(Optional.of(fixture.other));

        FraudAction split = create(fixture, FraudActionType.SPLIT_TRANSFER, List.of(
                target(fixture.intermediate.getId(), new BigDecimal("60.00")),
                target(fixture.other.getId(), new BigDecimal("40.00"))));
        execute(fixture, split);

        assertEquals(new BigDecimal("0.00"), fixture.sourcePosition.getAmount());
        assertEquals(new BigDecimal("60.00"), positionAt(fixture.scenario, fixture.intermediate).getAmount());
        assertEquals(new BigDecimal("40.00"), positionAt(fixture.scenario, fixture.other).getAmount());
        assertEquals("ACTIVE", fixture.scenario.getStatus());

        fixture.scenario.setTurn(FraudTurn.FRAUDSTER);
        FraudAction wait = create(fixture, FraudActionType.WAIT, List.of());
        execute(fixture, wait);

        ArgumentCaptor<List<Transaction>> transactions = ArgumentCaptor.forClass(List.class);
        verify(transactionRepository, times(1)).saveAll(transactions.capture());
        assertEquals(2, transactions.getValue().size());
        assertTrue(transactions.getValue().stream().allMatch(transaction ->
                Set.of("BANK_TRANSFER", "UPI", "ONLINE_PAYMENT", "CHEQUE", "CASH")
                        .contains(transaction.getChannel())));
        assertEquals(FraudTurn.INVESTIGATOR, fixture.scenario.getTurn());
        assertEquals(3, fixture.scenario.getInvestigatorActionsRemaining());
        verify(backgroundTransactionService, times(2))
                .generateForSuccessfulAction(eq(fixture.scenario), any(FraudAction.class));
    }

    private FraudAction create(Fixture fixture, FraudActionType type,
                               List<FraudsterActionTargetRequest> targets) {
        return create(fixture, type, targets, fixture.sourcePosition);
    }

    private FraudAction create(Fixture fixture, FraudActionType type,
                               List<FraudsterActionTargetRequest> targets,
                               FraudPosition sourcePosition) {
        FraudsterActionRequest request = new FraudsterActionRequest();
        request.setScenarioId(fixture.scenario.getId());
        request.setActionType(type);
        request.setSourcePositionId(sourcePosition.getId());
        request.setTargets(targets);
        Set<Long> eligible = new HashSet<>();
        targets.forEach(target -> {
            if (target != null && target.getDestinationCompanyId() != null) {
                eligible.add(target.getDestinationCompanyId());
            }
        });
        org.mockito.Mockito.lenient().when(companyRelationshipService.eligibleIntermediateCompanyIds(
                sourcePosition.getCompany().getId(), fixture.scenario.getTargetCompany().getId()))
                .thenReturn(eligible);
        when(scenarioRepository.findById(fixture.scenario.getId())).thenReturn(Optional.of(fixture.scenario));
        lenient().when(actionRepository.save(any(FraudAction.class))).thenAnswer(invocation -> {
            FraudAction action = invocation.getArgument(0);
            ReflectionTestUtils.setField(action, "id", 100L + fixture.scenario.getStep());
            return action;
        });
        return service.createAction(request);
    }

    private void execute(Fixture fixture, FraudAction action) {
        when(actionRepository.findById(action.getId())).thenReturn(Optional.of(action));
        when(scenarioRepository.findById(fixture.scenario.getId())).thenReturn(Optional.of(fixture.scenario));
        service.executeAction(action.getId());
    }

    private void assertTransaction(Company source, Company destination, String amount) {
        ArgumentCaptor<List<Transaction>> transactions = ArgumentCaptor.forClass(List.class);
        verify(transactionRepository).saveAll(transactions.capture());
        assertEquals(1, transactions.getValue().size());
        Transaction transaction = transactions.getValue().get(0);
        assertEquals(source.getId(), transaction.getSourceCompany().getId());
        assertEquals(destination.getId(), transaction.getDestinationCompany().getId());
        assertEquals(new BigDecimal(amount), transaction.getAmount());
        assertTrue(Set.of("BANK_TRANSFER", "UPI", "ONLINE_PAYMENT", "CHEQUE", "CASH")
                .contains(transaction.getChannel()));
    }

    private FraudsterActionTargetRequest target(Long companyId, BigDecimal amount) {
        FraudsterActionTargetRequest target = new FraudsterActionTargetRequest();
        target.setDestinationCompanyId(companyId);
        target.setAmount(amount);
        return target;
    }

    private FraudPosition positionAt(FraudScenario scenario, Company company) {
        return scenario.getPositions().stream()
                .filter(position -> position.getCompany().getId().equals(company.getId()))
                .findFirst().orElse(null);
    }

    private Fixture fixture(String amount) {
        Company source = company(1L);
        Company target = company(2L);
        Company intermediate = company(3L);
        Company other = company(4L);
        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", 10L);
        scenario.setSourceCompany(source);
        scenario.setTargetCompany(target);
        scenario.setTargetAmount(new BigDecimal(amount));
        scenario.setStatus("ACTIVE");
        scenario.setStep(0);
        scenario.setTurn(FraudTurn.FRAUDSTER);
        FraudPosition sourcePosition = new FraudPosition();
        ReflectionTestUtils.setField(sourcePosition, "id", 20L);
        sourcePosition.setScenario(scenario);
        sourcePosition.setCompany(source);
        sourcePosition.setAmount(new BigDecimal(amount));
        scenario.getPositions().add(sourcePosition);
        return new Fixture(scenario, source, target, intermediate, other, sourcePosition);
    }

    private Company company(Long id) {
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", id);
        return company;
    }

    private record Fixture(FraudScenario scenario, Company source, Company target,
                           Company intermediate, Company other, FraudPosition sourcePosition) { }
}
