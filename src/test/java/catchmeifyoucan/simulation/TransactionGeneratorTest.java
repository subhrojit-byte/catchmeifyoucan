package catchmeifyoucan.simulation;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.entity.TransactionOrigin;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Set;
import java.util.ArrayList;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TransactionGeneratorTest {

    @Test
    void generatedEnvironmentTransactionsHaveKnownChannels() {
        List<Company> companies = List.of(company("A"), company("B"), company("C"), company("D"),
                company("E"), company("F"), company("G"), company("H"));
        List<Transaction> transactions = new TransactionGenerator(7L)
                .generateTransactions(companies, 10);
        Set<String> channels = Set.of("BANK_TRANSFER", "UPI", "ONLINE_PAYMENT", "CHEQUE", "CASH");

        assertFalse(transactions.isEmpty());
        assertTrue(transactions.stream().allMatch(transaction -> channels.contains(transaction.getChannel())));
        assertTrue(transactions.stream().allMatch(transaction ->
                transaction.getOrigin() == TransactionOrigin.INITIAL_BACKGROUND));
    }

    @Test
    void sameSeedAndCompaniesProduceSameTransactionsRegardlessOfInputOrder() {
        List<Company> companies = new ArrayList<>(List.of(
                company("A"), company("B"), company("C"), company("D"),
                company("E"), company("F"), company("G"), company("H")));
        List<Transaction> first = new TransactionGenerator(7L).generateTransactions(companies, 10);
        List<Company> reversed = new ArrayList<>(companies);
        java.util.Collections.reverse(reversed);
        List<Transaction> second = new TransactionGenerator(7L).generateTransactions(reversed, 10);

        assertEquals(first.size(), second.size());
        for (int i = 0; i < first.size(); i++) {
            assertEquals(first.get(i).getSourceCompany().getCompanyName(),
                    second.get(i).getSourceCompany().getCompanyName());
            assertEquals(first.get(i).getDestinationCompany().getCompanyName(),
                    second.get(i).getDestinationCompany().getCompanyName());
            assertEquals(first.get(i).getAmount(), second.get(i).getAmount());
            assertEquals(first.get(i).getChannel(), second.get(i).getChannel());
            assertEquals(first.get(i).getTimestamp(), second.get(i).getTimestamp());
        }
    }

    @Test
    void transactionPatternsDoNotDependOnShellLabels() {
        List<Company> legitimate = companiesWithLabels(false);
        List<Company> shell = companiesWithLabels(true);
        List<Transaction> first = new TransactionGenerator(19L).generateTransactions(legitimate, 20);
        List<Transaction> second = new TransactionGenerator(19L).generateTransactions(shell, 20);

        assertEquals(first.size(), second.size());
        for (int i = 0; i < first.size(); i++) {
            assertEquals(first.get(i).getSourceCompany().getCompanyName(),
                    second.get(i).getSourceCompany().getCompanyName());
            assertEquals(first.get(i).getDestinationCompany().getCompanyName(),
                    second.get(i).getDestinationCompany().getCompanyName());
            assertEquals(first.get(i).getAmount(), second.get(i).getAmount());
            assertEquals(first.get(i).getChannel(), second.get(i).getChannel());
        }
    }

    private List<Company> companiesWithLabels(boolean shell) {
        return List.of(company("A", shell), company("B", shell), company("C", shell),
                company("D", shell), company("E", shell), company("F", shell),
                company("G", shell), company("H", shell));
    }

    private Company company(String name) {
        return company(name, false);
    }

    private Company company(String name, boolean shell) {
        Company company = new Company();
        company.setCompanyName(name);
        company.setAnnualRevenue(new BigDecimal("1000000.00"));
        company.setShellCompany(shell);
        return company;
    }
}
