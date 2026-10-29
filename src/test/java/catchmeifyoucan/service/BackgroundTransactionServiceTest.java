package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudAction;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.entity.TransactionOrigin;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudActionRepository;
import catchmeifyoucan.repository.TransactionRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class BackgroundTransactionServiceTest {

    @Mock private CompanyRepository companyRepository;
    @Mock private TransactionRepository transactionRepository;
    @Mock private FraudActionRepository fraudActionRepository;

    @Test
    void successfulActionGetsOneDeterministicTickAndRetryDoesNotDuplicateIt() {
        Company first = company(1L, "A");
        Company second = company(2L, "B");
        when(companyRepository.findAll()).thenReturn(List.of(second, first));
        when(fraudActionRepository.save(any(FraudAction.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        FraudScenario scenario = new FraudScenario();
        ReflectionTestUtils.setField(scenario, "id", 10L);
        scenario.setStep(3);
        FraudAction action = new FraudAction();
        action.setStep(2);

        BackgroundTransactionService service = new BackgroundTransactionService(
                companyRepository, transactionRepository, fraudActionRepository, 2, 77L);
        service.generateForSuccessfulAction(scenario, action);
        service.generateForSuccessfulAction(scenario, action);

        ArgumentCaptor<List<Transaction>> captor = ArgumentCaptor.forClass(List.class);
        verify(transactionRepository, times(1)).saveAll(captor.capture());
        assertEquals(2, captor.getValue().size());
        assertTrue(captor.getValue().stream().allMatch(transaction ->
                transaction.getOrigin() == TransactionOrigin.BACKGROUND));
        assertTrue(captor.getValue().stream().allMatch(transaction ->
                transaction.getScenario() == scenario && transaction.getFraudAction() == null));
        assertTrue(Boolean.TRUE.equals(action.getBackgroundTransactionsGenerated()));
        verify(fraudActionRepository, times(1)).save(action);
    }

    private Company company(Long id, String name) {
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", id);
        company.setCompanyName(name);
        company.setAnnualRevenue(new BigDecimal("1000000.00"));
        return company;
    }
}
