package catchmeifyoucan.service;

import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.TransactionRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class TransactionServiceTest {

    @Mock private TransactionRepository transactionRepository;
    @Mock private FraudScenarioRepository scenarioRepository;

    @Test
    void scenarioHistoryUsesOnlyScenarioLinkedTransactions() {
        Transaction first = new Transaction();
        Transaction second = new Transaction();
        when(scenarioRepository.existsById(4L)).thenReturn(true);
        when(transactionRepository.findByScenarioIdOrderByTimestampAscIdAsc(4L))
                .thenReturn(List.of(first, second));

        List<Transaction> result = new TransactionService(
                transactionRepository, scenarioRepository).getScenarioTransactions(4L);

        assertEquals(List.of(first, second), result);
        verify(transactionRepository).findByScenarioIdOrderByTimestampAscIdAsc(4L);
    }

    @Test
    void missingScenarioIsRejectedWithoutQueryingHistory() {
        when(scenarioRepository.existsById(4L)).thenReturn(false);

        assertThrows(IllegalArgumentException.class, () -> new TransactionService(
                transactionRepository, scenarioRepository).getScenarioTransactions(4L));
    }
}
