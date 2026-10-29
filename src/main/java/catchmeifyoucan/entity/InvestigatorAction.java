package catchmeifyoucan.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

@Getter
@Entity
@Table(name = "investigator_actions")
public class InvestigatorAction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @JsonIgnore
    @ManyToOne
    @JoinColumn(name = "scenario_id", nullable = false)
    private FraudScenario scenario;

    @Setter
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private InvestigatorActionType actionType;

    @Setter
    @ManyToOne
    @JoinColumn(name = "company_id")
    private Company targetCompany;

    @Setter
    @ManyToOne
    @JoinColumn(name = "transaction_id")
    private Transaction transaction;

    @Setter
    @Column(nullable = false)
    private int step;

    @Setter
    @Column(name = "flag_correct")
    private Boolean flagCorrect;

    public InvestigatorAction() {
    }
}
