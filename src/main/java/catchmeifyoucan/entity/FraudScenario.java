package catchmeifyoucan.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

@Getter
@Entity
@Table(name = "fraud_scenarios")
public class FraudScenario {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @ManyToOne
    @JoinColumn(name = "source_company_id", nullable = false)
    private Company sourceCompany;

    @Setter
    @ManyToOne
    @JoinColumn(name = "target_company_id", nullable = false)
    private Company targetCompany;

    @Setter
    @Column(nullable = false, precision = 19, scale = 2)
    private BigDecimal targetAmount;

    @OneToMany(
            mappedBy = "scenario",
            cascade = CascadeType.ALL,
            orphanRemoval = true
    )
    private List<FraudPosition> positions =
            new ArrayList<>();

    @OneToMany(
            mappedBy = "scenario",
            cascade = CascadeType.ALL,
            orphanRemoval = true
    )
    private List<FraudAction> actions =
            new ArrayList<>();

    @OneToMany(
            mappedBy = "scenario",
            cascade = CascadeType.ALL,
            orphanRemoval = true
    )
    @JsonIgnore
    private List<InvestigatorAction> investigatorActions =
            new ArrayList<>();

    @Setter
    @Column(nullable = false)
    private String status;

    @Setter
    @Column(nullable = false)
    private int step;

    @Setter
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private FraudTurn turn = FraudTurn.FRAUDSTER;

    @Setter
    @Column(nullable = false)
    private int investigatorActionsRemaining;

    /**
     * Nullable for compatibility with scenarios persisted before this marker
     * existed. A true value means the transfer objective is achieved, while
     * status remains ACTIVE until the final investigator turn is completed.
     */
    @Setter
    @Column(name = "financial_objective_achieved")
    private Boolean financialObjectiveAchieved = false;

    public FraudScenario() {
    }

}
